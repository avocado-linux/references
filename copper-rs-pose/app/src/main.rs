//! YOLOv8 Pose Estimation Demo for Copper
//!
//! This example demonstrates real-time pose estimation using:
//! - GStreamer (V4L2) camera input
//! - YOLOv8-pose model via Candle (HuggingFace ML framework)
//! - Rerun visualization for displaying results
//!
//! Based on the copper-rs `cu_human_pose` example. See getting_started.md.

mod image;
mod payloads;
mod tasks;
mod yolo;

use std::fs;
use std::path::Path;
use std::process::ExitCode;
use std::thread;
use std::time::Duration;

use cu29::prelude::*;

// Re-export for RON config visibility
pub use payloads::*;
pub use tasks::*;

// Size of one log slab. cu29 makes a new slab file when one is full.
const SLAB_SIZE: Option<usize> = Some(256 * 1024 * 1024); // 256 MB

// The root filesystem is read-only. systemd makes this directory (StateDirectory=).
const LOG_DIR: &str = "/var/lib/copper-rs-pose";
const LOG_PATH: &str = "/var/lib/copper-rs-pose/human-pose.copper";
// The slabs of the run before this one. cu29 truncates slab 0 when it opens it.
const PREVIOUS_LOG_DIR: &str = "/var/lib/copper-rs-pose/previous";
// Written when a run lasts MIN_RUN. A run that fails at startup does not write it.
const RUN_MARKER: &str = "/var/lib/copper-rs-pose/last-run-lasted";
const MIN_RUN: Duration = Duration::from_secs(30);

#[copper_runtime(config = "copperconfig.ron")]
struct YoloPoseDemoApplication {}

/// Moves the slabs of the last run into `PREVIOUS_LOG_DIR`, so that a restart
/// after a failure does not erase the log of the failed run. The disk keeps two
/// runs at most: the slabs that were in `PREVIOUS_LOG_DIR` are deleted.
///
/// If the last run stopped before MIN_RUN, the slabs stay where they are and
/// cu29 overwrites them. Thus a restart loop (for example, with no camera) does
/// not push the log of the run that failed out of `PREVIOUS_LOG_DIR`.
fn keep_previous_log() -> std::io::Result<()> {
    if !Path::new(RUN_MARKER).exists() {
        return Ok(());
    }

    let slabs: Vec<_> = fs::read_dir(LOG_DIR)?
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with("human-pose_") && name.ends_with(".copper"))
        })
        .collect();
    if slabs.is_empty() {
        return Ok(());
    }

    let previous = Path::new(PREVIOUS_LOG_DIR);
    if previous.exists() {
        fs::remove_dir_all(previous)?;
    }
    fs::create_dir(previous)?;
    for slab in slabs {
        if let Some(name) = slab.file_name() {
            fs::rename(&slab, previous.join(name))?;
        }
    }
    fs::remove_file(RUN_MARKER)
}

fn main() -> ExitCode {
    fs::create_dir_all(LOG_DIR).expect("Failed to create logs directory");

    // A failure here only costs the old log, so the app still starts.
    if let Err(e) = keep_previous_log() {
        eprintln!("copper-rs-pose: could not keep the log of the last run: {e}");
    }

    thread::spawn(|| {
        thread::sleep(MIN_RUN);
        if let Err(e) = fs::write(RUN_MARKER, b"") {
            eprintln!("copper-rs-pose: could not write {RUN_MARKER}: {e}");
        }
    });

    // Build the application from RON config
    let application = YoloPoseDemoApplication::builder()
        .with_log_path(LOG_PATH, SLAB_SIZE)
        .expect("Failed to set up Copper logging")
        .build()
        .expect("Failed to build application");

    // `run` starts the tasks itself.
    if let Err(e) = application.run_until_shutdown() {
        error!("Error during iteration: {}", e.error.to_string());
        // In a release build, error! goes only to the .copper log. Tell systemd too.
        eprintln!("copper-rs-pose: {}", e.error);
        // Return (do not call process::exit) so that `e` is dropped and the
        // logger closes the .copper file.
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}
