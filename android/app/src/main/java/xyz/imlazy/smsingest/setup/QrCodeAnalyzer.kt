package xyz.imlazy.smsingest.setup

import androidx.annotation.OptIn
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.common.InputImage

/**
 * Bridges CameraX frames to ML Kit's on-device barcode scanner and reports the
 * raw payload of the first QR code found on each frame. Does not de-duplicate
 * repeat detections across frames — QrScanScreen's caller is responsible for
 * only acting on the first callback.
 */
class QrCodeAnalyzer(
    private val scanner: BarcodeScanner,
    private val onQrDetected: (String) -> Unit,
) : ImageAnalysis.Analyzer {

    @OptIn(ExperimentalGetImage::class)
    override fun analyze(imageProxy: ImageProxy) {
        val mediaImage = imageProxy.image
        if (mediaImage == null) {
            imageProxy.close()
            return
        }
        val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
        scanner.process(image)
            .addOnSuccessListener { barcodes -> barcodes.firstNotNullOfOrNull { it.rawValue }?.let(onQrDetected) }
            .addOnCompleteListener { imageProxy.close() }
    }
}
