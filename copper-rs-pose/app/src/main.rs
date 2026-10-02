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

use cu29::prelude::*;

// Re-export for RON config visibility
pub use payloads::*;
pub use tasks::*;

// Size of one log slab. cu29 makes a new slab file when one is full.
const SLAB_SIZE: Option<usize> = Some(256 * 1024 * 1024); // 256 MB

#[copper_runtime(config = "copperconfig.ron")]
struct YoloPoseDemoApplication {}

fn main() -> ExitCode {
    // The root filesystem is read-only. systemd makes this directory (StateDirectory=).
    let logger_path = "/var/lib/copper-rs-pose/human-pose.copper";
    if let Some(parent) = Path::new(logger_path).parent()
        && !parent.exists()
    {
        fs::create_dir_all(parent).expect("Failed to create logs directory");
    }

    // Build the application from RON config
    let application = YoloPoseDemoApplication::builder()
        .with_log_path(logger_path, SLAB_SIZE)
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
