import Foundation
import Vision
import ImageIO
let url=URL(fileURLWithPath:CommandLine.arguments[1])
guard let source=CGImageSourceCreateWithURL(url as CFURL,nil), let image=CGImageSourceCreateImageAtIndex(source,0,nil) else {fatalError("Cannot open frame")}
let request=VNDetectBarcodesRequest();request.symbologies=[.qr]
try VNImageRequestHandler(cgImage:image).perform([request])
let values=(request.results ?? []).compactMap{$0.payloadStringValue}
print(values.joined(separator:"\n"))
if !values.contains(CommandLine.arguments[2]) {exit(1)}
