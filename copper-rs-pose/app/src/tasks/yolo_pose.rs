//! YOLOv8 Pose estimation Copper task

use crate::payloads::CuPoses;
use crate::yolo::{Multiples, YoloV8Pose, preprocess_image, process_predictions};
use candle_core::{DType, Device};
use candle_nn::{Module, VarBuilder};
use cu_sensor_payloads::CuImage;
use cu29::prelude::*;

/// YOLOv8 Pose estimation task
///
/// Processes incoming camera images and outputs detected poses with keypoints.
#[derive(Reflect)]
#[reflect(from_reflect = false)]
pub struct YoloPose {
    #[reflect(ignore)]
    model: YoloV8Pose,
    #[reflect(ignore)]
    device: Device,
    conf_threshold: f32,
    iou_threshold: f32,
}

impl Freezable for YoloPose {}

impl CuTask for YoloPose {
    type Resources<'r> = ();
    type Input<'m> = input_msg!(CuImage<Vec<u8>>);
    type Output<'m> = output_msg!(CuPoses);

    fn new(config: Option<&ComponentConfig>, _resources: Self::Resources<'_>) -> CuResult<Self>
    where
        Self: Sized,
    {
        // Parse configuration
        let config = config.ok_or_else(|| CuError::from("YoloPose requires configuration"))?;

        let variant = config
            .get::<String>("variant")?
            .unwrap_or_else(|| "yolov8n-pose".to_string());

        let conf_threshold = config.get::<f64>("conf_threshold")?.unwrap_or(0.25) as f32;
        let iou_threshold = config.get::<f64>("iou_threshold")?.unwrap_or(0.7) as f32;

        // Determine model size from variant
        let multiples = match variant.as_str() {
            "yolov8n-pose" => Multiples::n(),
            "yolov8s-pose" => Multiples::s(),
            "yolov8m-pose" => Multiples::m(),
            "yolov8l-pose" => Multiples::l(),
            "yolov8x-pose" => Multiples::x(),
            _ => {
                return Err(CuError::from(format!(
                    "Unknown variant: {}. Use yolov8[n|s|m|l|x]-pose",
                    variant
                )));
            }
        };

        // Select device based on feature flags
        #[cfg(feature = "cuda")]
        let device = Device::new_cuda(0).unwrap_or(Device::Cpu);

        #[cfg(not(feature = "cuda"))]
        let device = Device::Cpu;

        // The weights are installed in the extension at build time. The device
        // does not download them.
        let model_path = config
            .get::<String>("model_path")?
            .ok_or_else(|| CuError::from("YoloPose requires model_path"))?;

        // Load the model
        // SAFETY: The safetensors file is memory-mapped and only read by VarBuilder.
        let vb = unsafe {
            VarBuilder::from_mmaped_safetensors(&[model_path], DType::F32, &device)
                .map_err(|e| CuError::new_with_cause("Failed to load model weights", e))?
        };

        let model = YoloV8Pose::load(vb, multiples, 1, (17, 3))
            .map_err(|e| CuError::new_with_cause("Failed to build YOLOv8 model", e))?;

        Ok(Self {
            model,
            device,
            conf_threshold,
            iou_threshold,
        })
    }

    fn process(
        &mut self,
        _ctx: &CuContext,
        input: &Self::Input<'_>,
        output: &mut Self::Output<'_>,
    ) -> CuResult<()> {
        let Some(image) = input.payload() else {
            // No image received; don't emit poses to avoid clearing downstream overlays.
            output.clear_payload();
            return Ok(());
        };

        // Preprocess the image
        let (tensor, model_w, model_h) = preprocess_image(image, &self.device)
            .map_err(|e| CuError::new_with_cause("Failed to preprocess image", e))?;

        // Run inference
        let predictions = self
            .model
            .forward(&tensor)
            .map_err(|e| CuError::new_with_cause("Model inference failed", e))?
            .squeeze(0)
            .map_err(|e| CuError::new_with_cause("Failed to squeeze predictions", e))?;

        // Postprocess predictions
        let poses = process_predictions(
            &predictions,
            image.format.width,
            image.format.height,
            model_w,
            model_h,
            self.conf_threshold,
            self.iou_threshold,
        );

        output.set_payload(poses);
        output.tov = input.tov;

        Ok(())
    }
}
