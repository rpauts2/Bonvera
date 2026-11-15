#!/usr/bin/env python3
"""Wrap an official card render in a BONVERA visual stage without editing the card.

The source image is embedded byte-for-byte in SVG. It is not recolored, redrawn,
warped, cropped or retouched. The composition adds a BONVERA stage around the
original asset. The script does not verify product details or image-use rights.
"""
from __future__ import annotations
import argparse
import base64
from pathlib import Path
import mimetypes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--accent', default='#e7b94f')
    parser.add_argument('--rotation', type=float, default=0.0, help='Rotate the whole source render subtly inside the scene')
    args = parser.parse_args()
    source = args.input.resolve()
    if not source.is_file():
        raise SystemExit(f'Input image not found: {source}')
    mime = mimetypes.guess_type(source.name)[0] or 'image/png'
    payload = base64.b64encode(source.read_bytes()).decode('ascii')
    data_uri = f'data:{mime};base64,{payload}'
    accent = args.accent
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1800" height="1040" viewBox="0 0 1800 1040">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#080b20"/><stop offset=".52" stop-color="#17133b"/><stop offset="1" stop-color="#080d1c"/></linearGradient>
  <radialGradient id="violet"><stop stop-color="#773bff" stop-opacity=".45"/><stop offset="1" stop-color="#773bff" stop-opacity="0"/></radialGradient>
  <radialGradient id="gold"><stop stop-color="{accent}" stop-opacity=".32"/><stop offset="1" stop-color="{accent}" stop-opacity="0"/></radialGradient>
  <linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#26204d" stop-opacity=".2"/><stop offset="1" stop-color="#070a16" stop-opacity=".95"/></linearGradient>
  <filter id="blur"><feGaussianBlur stdDeviation="42"/></filter>
  <filter id="shadow" x="-30%" y="-30%" width="160%" height="180%"><feGaussianBlur in="SourceAlpha" stdDeviation="26" result="b"/><feOffset dy="35" result="o"/><feColorMatrix in="o" type="matrix" values="0 0 0 0 0.01 0 0 0 0 0.01 0 0 0 0 0.06 0 0 0 .78 0" result="s"/><feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{accent}" stop-opacity=".65"/><stop offset=".5" stop-color="#fff0b7" stop-opacity=".12"/><stop offset="1" stop-color="{accent}" stop-opacity=".05"/></linearGradient>
</defs>
<rect width="1800" height="1040" fill="url(#bg)"/>
<ellipse cx="1250" cy="410" rx="560" ry="440" fill="url(#violet)" filter="url(#blur)"/>
<ellipse cx="500" cy="790" rx="480" ry="300" fill="url(#gold)" filter="url(#blur)"/>
<g fill="none" stroke="{accent}" opacity=".13"><circle cx="1370" cy="420" r="340" stroke-width="3"/><circle cx="1370" cy="420" r="390" stroke-width="2"/><circle cx="1370" cy="420" r="445" stroke-width="1"/></g>
<path d="M0 790 Q900 700 1800 790 V1040 H0Z" fill="url(#floor)"/>
<ellipse cx="1110" cy="845" rx="560" ry="85" fill="{accent}" opacity=".09" filter="url(#blur)"/>
<path d="M620 850 L820 770 H1450 L1630 850 L1450 910 H800Z" fill="#10152d" stroke="url(#rim)" stroke-width="3" opacity=".9"/>
<path d="M760 910 L850 870 H1430 L1510 910 L1430 950 H850Z" fill="#090d1d" stroke="{accent}" stroke-opacity=".28" stroke-width="2"/>
<image x="350" y="125" width="1120" height="700" preserveAspectRatio="xMidYMid meet" transform="rotate({args.rotation} 910 475)" xlink:href="{data_uri}" filter="url(#shadow)"/>
<g fill="{accent}" opacity=".75"><circle cx="330" cy="280" r="5"/><circle cx="1530" cy="250" r="4"/><circle cx="1480" cy="670" r="6"/><circle cx="270" cy="690" r="3"/></g>
</svg>'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding='utf-8')
    print(f'Wrote {args.output} (source bytes embedded unchanged)')

if __name__ == '__main__':
    main()
