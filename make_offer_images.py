from pathlib import Path
import yaml, hashlib, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
ROOT=Path(__file__).resolve().parent
D=ROOT/'assets'/'offers'
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

def font(size,bold=False): return ImageFont.truetype(BOLD if bold else FONT,size)

def mix(a,b,t): return tuple(int(a[i]*(1-t)+b[i]*t) for i in range(3))

def make(row):
    code=row['code']; cat=row['category']; brand=row['name']; reward=row['reward']; condition=row['condition']
    seed=int(hashlib.sha256(code.encode()).hexdigest()[:8],16)
    palettes={
        'cards':((12,21,48),(47,86,170),(30,220,200)),
        'bk':((16,12,40),(75,35,150),(255,155,40)),
        'mfo':((13,27,38),(20,105,100),(100,220,170)),
        'cpl':((28,16,44),(104,43,130),(255,185,75)),
    }
    c1,c2,accent=palettes[cat]
    c1=mix(c1,(seed>>16&255,seed>>8&255,seed&255),.14)
    W,H=900,520
    import numpy as np
    xx=np.linspace(0,1,W,dtype=np.float32)[None,:,None]
    yy=np.linspace(0,1,H,dtype=np.float32)[:,None,None]
    t=np.clip(.68*xx+.32*yy,0,1)*.9
    gy=np.linspace(0,H-1,H,dtype=np.float32)[:,None]
    gx=np.linspace(0,W-1,W,dtype=np.float32)[None,:]
    glow=np.clip(1-np.sqrt(((gx-690)/600)**2+((gy-70)/480)**2),0,1)[...,None]*.2
    base=np.array(c1,dtype=np.float32)[None,None,:]*(1-t)+np.array(c2,dtype=np.float32)[None,None,:]*t
    base=base*(1-glow)+np.array(accent,dtype=np.float32)[None,None,:]*glow
    im=Image.fromarray(np.uint8(np.clip(base,0,255)),'RGB')
    d=ImageDraw.Draw(im,'RGBA')
    # geometric lights and texture
    for i in range(18):
        x=(seed*(i+7)*7919)%(W+100)-50; y=(seed*(i+11)*3571)%(H+100)-50
        r=15+(i*13)%70
        d.ellipse((x-r,y-r,x+r,y+r),outline=(*accent,30),width=2)
    d.polygon([(0,400),(520,140),(900,260),(900,520),(0,520)],fill=(0,0,0,58))
    d.line([(0,440),(900,110)],fill=(*accent,65),width=3)
    d.rounded_rectangle((30,28,870,492),radius=28,outline=(*accent,150),width=3,fill=(7,10,25,45))
    # visual object on right: card / soccer ball / money / document
    cx,cy=690,278
    if cat=='cards':
        d.rounded_rectangle((525,190,825,375),radius=28,fill=(8,12,25,240),outline=(*accent,255),width=4)
        d.rounded_rectangle((555,226,610,269),radius=7,fill=(220,190,100,245))
        d.line((558,246,608,246),fill=(75,65,40,255),width=2)
        d.arc((735,285,800,350),180,350,fill=(220,220,235,220),width=5)
        d.text((550,300),'CARD',font=font(23,True),fill=(225,235,255,235))
    elif cat=='bk':
        d.ellipse((570,175,815,420),fill=(242,246,250,245),outline=(*accent,255),width=5)
        d.polygon([(670,205),(715,220),(728,264),(690,292),(650,265),(648,225)],fill=(18,23,40,255))
        d.polygon([(604,285),(650,265),(690,292),(676,345),(625,350)],fill=(18,23,40,255))
        d.polygon([(728,264),(775,275),(790,325),(748,355),(690,292)],fill=(18,23,40,255))
        d.arc((587,190,800,402),0,360,fill=(*accent,150),width=3)
    elif cat=='mfo':
        d.ellipse((605,185,790,370),fill=(247,190,70,245),outline=(255,230,140,255),width=5)
        d.text((657,220),'₽',font=font(112,True),fill=(80,50,18,255))
        d.rounded_rectangle((550,360,830,410),radius=12,fill=(10,40,50,210),outline=(*accent,230),width=3)
        d.text((576,368),'ВЫДАЧА',font=font(25,True),fill=(230,255,245,255))
    else:
        d.rounded_rectangle((585,165,790,415),radius=20,fill=(245,247,255,245),outline=(*accent,255),width=5)
        for yy in (220,270,320):
            d.line((625,yy,750,yy),fill=(55,75,105,190),width=7)
        d.ellipse((722,330,800,408),fill=(20,190,135,250),outline=(255,255,255,255),width=3)
        d.line((742,368,758,384),fill=(255,255,255,255),width=7); d.line((758,384,785,347),fill=(255,255,255,255),width=7)
    tag={'cards':'БАНКОВСКАЯ КАРТА','bk':'БУКМЕКЕРСКОЕ ПРЕДЛОЖЕНИЕ','mfo':'ВЫДАЧА ЗАЙМА','cpl':'ЗАЯВКА / ЛИД'}[cat]
    d.text((65,62),tag,font=font(22,True),fill=(*accent,255))
    # wrap brand title to two lines max
    name=brand
    while d.textbbox((0,0),name,font=font(46,True))[2]>440 and ' ' in name:
        parts=name.split(' '); name=' '.join(parts[:-1])
    d.text((65,124),name,font=font(44,True),fill=(250,250,255,255),stroke_width=1,stroke_fill=(0,0,0,80))
    d.text((65,210),f'{reward:,}'.replace(',',' ')+' ₽',font=font(54,True),fill=(255,220,90,255))
    d.text((65,277),'ТВОЁ ВОЗНАГРАЖДЕНИЕ',font=font(19,True),fill=(225,235,255,230))
    # condition shorten by word-safe wrap
    words=condition.split(); lines=[]; line=''
    for w in words:
        cand=(line+' '+w).strip()
        if d.textbbox((0,0),cand,font=font(17))[2]>420 and line:
            lines.append(line); line=w
        else: line=cand
        if len(lines)>=2: break
    if line and len(lines)<3: lines.append(line)
    y=340
    for ln in lines[:3]:
        d.text((65,y),ln,font=font(17),fill=(235,240,255,220)); y+=28
    d.text((65,452),f'Cashback Bot  •  {code.upper()}',font=font(16,True),fill=(225,230,255,185))
    path=D/cat/f'{code}.jpg'; path.parent.mkdir(parents=True,exist_ok=True)
    im.save(path,'JPEG',quality=90,optimize=True)

rows=yaml.safe_load((ROOT/'catalog.yaml').read_text(encoding='utf-8'))['offers']
for row in rows: make(row)
print('images',len(rows),'saved',sum(1 for r in rows if (D/r['category']/f"{r['code']}.jpg").exists()))
