import numpy as np

def ema(s, w):
    s=np.asarray(s,dtype=float)
    a=2/(w+1); y=np.zeros_like(s); y[0]=s[0]
    for i in range(1,len(s)): y[i]=a*s[i]+(1-a)*y[i-1]
    return y

def rsi(s, w=7):
    s=np.asarray(s,dtype=float); d=np.diff(s); u=np.where(d>0,d,0); v=np.where(d<0,-d,0)
    au=ema(u,w); av=ema(v,w); rs=np.divide(au,av,where=av!=0)
    return 100-100/(1+rs)

def atr(h,l,c,w=14):
    h,l,c=np.asarray(h),np.asarray(l),np.asarray(c)
    tr=np.maximum(h-l,np.abs(np.diff(c,prepend=c[0])-h),np.abs(np.diff(c,prepend=c[0])-l))
    return ema(tr,w)

def swing_low(l, n=2):
    l=np.asarray(l); out=[]
    for i in range(n,len(l)-n):
        if all(l[i]<l[i-j] and l[i]<l[i+j] for j in range(1,n+1)): out.append((i,l[i]))
    return out

def swing_high(h, n=2):
    h=np.asarray(h); out=[]
    for i in range(n,len(h)-n):
        if all(h[i]>h[i-j] and h[i]>h[i+j] for j in range(1,n+1)): out.append((i,h[i]))
    return out

def bullish_ob(o,h,l,c,v, min_body=0.008, vol_mult=1.5):
    """find last valid bullish order block: bearish candle before a strong impulse up"""
    n=len(c); idx=None
    mv=np.mean(v[-10:])*vol_mult if len(v)>=10 else 0
    for i in range(n-2, max(1,n-80), -1):
        if c[i]>o[i] and (c[i]-o[i])/o[i]>=min_body and v[i]>=mv: # impulse
            j=i-1
            if c[j]<o[j]: idx=j; break
    if idx is None: return None
    return (float(l[idx]), float(h[idx]))

def fvg(h,l):
    """last bullish fair value gap [high[i-1], low[i+1]] where low[i+1]>high[i-1]"""
    n=len(l)
    for i in range(n-2, max(1,n-60), -1):
        if l[i+1]>h[i-1]: return (float(h[i-1]), float(l[i+1]))
    return None

def engulfing_bull(o,c):
    n=len(o); i=n-1
    if i<1: return False
    if c[i-1]>=o[i-1] or c[i]<=o[i]: return False
    body_prev = o[i-1]-c[i-1]
    body_cur  = c[i]-o[i]
    return o[i]<=c[i-1] and c[i]>o[i-1] and body_cur>=1.8*body_prev
