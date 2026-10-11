#!/usr/bin/env python3
"""Correlate a rendered scrolling region to detect reversals and lateral shake.

Usage: python audit_motion.py VIDEO START DURATION WIDTH:HEIGHT:X:Y OUTPUT_JSON
Requires local numpy. Use a footage-only region, excluding changing captions.
Negative content dy means a naturally downward page scroll.
"""
import json
import subprocess
import sys
import numpy as np

filename,start,duration,crop,output=sys.argv[1:]
w,h,x,y=map(int,crop.split(':'))
raw=subprocess.run(['ffmpeg','-v','error','-ss',start,'-t',duration,'-i',filename,'-vf',f'crop={crop},fps=30,format=gray','-f','rawvideo','-'],check=True,capture_output=True).stdout
frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,h,w).astype(np.float32)
window=np.outer(np.hanning(h),np.hanning(w));shifts=[]
for before,after in zip(frames[:-1],frames[1:]):
    a=(before-before.mean())*window;b=(after-after.mean())*window
    corr=np.fft.ifft2(np.fft.fft2(b)*np.conj(np.fft.fft2(a))).real
    _,dy,dx=max((float(corr[dy%h,dx%w]),dy,dx) for dy in range(-24,25) for dx in range(-4,5))
    shifts.append({'dy':dy,'dx':dx})
assert shifts,'No frame pairs in the supplied region'
result={'artifact':filename,'start':float(start),'duration':float(duration),'crop':crop,'fps':30,'pairs':len(shifts),'shifts':shifts,'reversals':sum(s['dy']>1 for s in shifts),'maximum_lateral_shift':max(abs(s['dx']) for s in shifts),'dy_range':[min(s['dy'] for s in shifts),max(s['dy'] for s in shifts)]}
with open(output,'w') as f:json.dump(result,f,indent=2)
print(json.dumps({k:v for k,v in result.items() if k!='shifts'},indent=2))
if result['reversals']:sys.exit(1)
