import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count > 1 else { print("usage: ocr <image> [langs]"); exit(1) }
let path = args[1]
let langs = args.count > 2 ? args[2].split(separator: ",").map(String.init) : ["zh-Hans", "en-US"]

guard let img = NSImage(contentsOfFile: path),
      let tiff = img.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff),
      let cg = rep.cgImage else {
    print("cannot load \(path)"); exit(1)
}

let w = CGFloat(cg.width), h = CGFloat(cg.height)

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = langs
request.usesLanguageCorrection = false

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do { try handler.perform([request]) } catch { print("ocr error \(error)"); exit(1) }

guard let obs = request.results else { print("no results"); exit(0) }
for o in obs {
    guard let top = o.topCandidates(1).first else { continue }
    let bb = o.boundingBox  // normalized, origin bottom-left
    let x = bb.origin.x * w
    let y = (1 - bb.origin.y - bb.height) * h
    let bw = bb.width * w
    let bh = bb.height * h
    print("\(Int(x))\t\(Int(y))\t\(Int(bw))\t\(Int(bh))\t\(String(format: "%.2f", top.confidence))\t\(top.string)")
}
