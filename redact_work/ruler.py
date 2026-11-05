import sys
from PIL import Image, ImageDraw
p,x,y,w,h,out=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4]),int(sys.argv[5]),sys.argv[6]
scale=float(sys.argv[7]) if len(sys.argv)>7 else 1.5
im=Image.open(p).convert("RGB")
c=im.crop((x,y,x+w,y+h)).resize((int(w*scale),int(h*scale)),Image.LANCZOS)
d=ImageDraw.Draw(c)
for gx in range(0,c.width,20):
    sx=x+int(gx/scale)
    col=(255,0,0) if sx%100==0 else (120,190,255)
    d.line([(gx,0),(gx,c.height)],fill=col,width=1)
    if sx%100==0: d.text((gx+2,1),str(sx),fill=(255,0,0))
for gy in range(0,c.height,20):
    sy=y+int(gy/scale)
    col=(255,0,0) if sy%100==0 else (120,190,255)
    d.line([(0,gy),(c.width,gy)],fill=col,width=1)
    if sy%100==0: d.text((2,gy+1),str(sy),fill=(255,0,0))
c.save(out); print(out,c.size)
