#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <Vision/Vision.h>

static CGImageRef loadImage(NSString *path, size_t *W, size_t *H) {
    NSData *data = [NSData dataWithContentsOfFile:path];
    if (!data) return NULL;
    CGImageSourceRef src = CGImageSourceCreateWithData((__bridge CFDataRef)data, NULL);
    if (!src) return NULL;
    CGImageRef cg = CGImageSourceCreateImageAtIndex(src, 0, NULL);
    if (cg) { *W = CGImageGetWidth(cg); *H = CGImageGetHeight(cg); }
    return cg;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 2) { fprintf(stderr, "usage: ocr <image> [langs] [--search TERM]\n"); return 1; }
        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSArray *langs = @[@"zh-Hans", @"en-US"];
        NSString *search = nil;
        for (int i = 2; i < argc; i++) {
            NSString *a = [NSString stringWithUTF8String:argv[i]];
            if ([a isEqualToString:@"--search"] && i + 1 < argc) {
                search = [NSString stringWithUTF8String:argv[++i]];
            } else if (i == 2) {
                langs = [a componentsSeparatedByString:@","];
            }
        }

        size_t W = 0, H = 0;
        CGImageRef cg = loadImage(path, &W, &H);
        if (!cg) { fprintf(stderr, "cannot decode %s\n", argv[1]); return 1; }

        VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:cg options:@{}];
        VNRecognizeTextRequest *req = [[VNRecognizeTextRequest alloc] init];
        req.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
        req.recognitionLanguages = langs;
        req.usesLanguageCorrection = (search == nil);
        NSError *err = nil;
        [handler performRequests:@[req] error:&err];
        if (err) { fprintf(stderr, "ocr failed: %s\n", err.localizedDescription.UTF8String); return 1; }

        for (VNRecognizedTextObservation *o in req.results) {
            VNRecognizedText *top = [[o topCandidates:1] firstObject];
            if (!top) continue;
            NSString *s = top.string;
            if (search == nil) {
                CGRect bb = o.boundingBox;
                printf("%d\t%d\t%d\t%d\t%.2f\t%s\n", (int)llround(bb.origin.x * W),
                       (int)llround((1.0 - bb.origin.y - bb.size.height) * H),
                       (int)llround(bb.size.width * W), (int)llround(bb.size.height * H),
                       top.confidence, s.UTF8String);
            } else {
                NSRange r = [s rangeOfString:search];
                while (r.location != NSNotFound) {
                    VNRecognizedTextObservation *bo = [top boundingBoxForRange:r error:&err];
                    if (bo) {
                        CGRect bb = bo.boundingBox;
                        printf("%d\t%d\t%d\t%d\t%.2f\t%s\t%s\n",
                               (int)llround(bb.origin.x * W),
                               (int)llround((1.0 - bb.origin.y - bb.size.height) * H),
                               (int)llround(bb.size.width * W), (int)llround(bb.size.height * H),
                               top.confidence, [search UTF8String], s.UTF8String);
                    }
                    NSUInteger start = r.location + r.length;
                    if (start >= s.length) break;
                    r = [s rangeOfString:search options:0 range:NSMakeRange(start, s.length - start)];
                }
            }
        }
        CGImageRelease(cg);
    }
    return 0;
}
