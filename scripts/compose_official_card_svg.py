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
  <radialGradient id="gold"><stop stop-color="{accent}" stop-opacity=".42"/><stop offset="1" stop-color="{accent}" stop-opacity="0"/></radialGradient>
  <radialGradient id="cyan"><stop stop-color="#17d9f2" stop-opacity=".28"/><stop offset="1" stop-color="#17d9f2" stop-opacity="0"/></radialGradient>
  <linearGradient id="beam" x1="0" y1="1" x2="1" y2="0"><stop stop-color="{accent}" stop-opacity="0"/><stop offset=".5" stop-color="{accent}" stop-opacity=".24"/><stop offset="1" stop-color="#8a5cff" stop-opacity="0"/></linearGradient>
  <linearGradient id="platform" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#35366c"/><stop offset=".45" stop-color="#151a3b"/><stop offset="1" stop-color="#070b1c"/></linearGradient>
  <linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#26204d" stop-opacity=".2"/><stop offset="1" stop-color="#070a16" stop-opacity=".95"/></linearGradient>
  <filter id="blur"><feGaussianBlur stdDeviation="52"/></filter>
  <filter id="neon"><feGaussianBlur stdDeviation="13" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="shadow" x="-30%" y="-30%" width="160%" height="180%"><feGaussianBlur in="SourceAlpha" stdDeviation="26" result="b"/><feOffset dy="35" result="o"/><feColorMatrix in="o" type="matrix" values="0 0 0 0 0.01 0 0 0 0 0.01 0 0 0 0 0.06 0 0 0 .78 0" result="s"/><feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{accent}" stop-opacity=".65"/><stop offset=".5" stop-color="#fff0b7" stop-opacity=".12"/><stop offset="1" stop-color="{accent}" stop-opacity=".05"/></linearGradient>
</defs>
<rect width="1800" height="1040" fill="url(#bg)"/>
<ellipse cx="1260" cy="390" rx="650" ry="500" fill="url(#violet)" filter="url(#blur)"/>
<ellipse cx="520" cy="760" rx="560" ry="360" fill="url(#gold)" filter="url(#blur)"/>
<ellipse cx="330" cy="300" rx="390" ry="330" fill="url(#cyan)" filter="url(#blur)"/>
<path d="M0 160 L900 0 L1800 130 L1800 190 L0 240Z" fill="url(#beam)" opacity=".28"/>
<path d="M0 590 L900 400 L1800 530 L1800 580 L0 680Z" fill="url(#beam)" opacity=".16"/>
<g fill="none" stroke="{accent}" opacity=".18"><circle cx="1360" cy="410" r="300" stroke-width="2"/><circle cx="1360" cy="410" r="365" stroke-width="2"/><circle cx="1360" cy="410" r="430" stroke-width="1.5"/><circle cx="1360" cy="410" r="495" stroke-width="1"/></g>
<g fill="none" stroke="#8b65ff" opacity=".22"><path d="M70 830 Q900 280 1730 830" stroke-width="2"/><path d="M0 900 Q900 360 1800 900" stroke-width="1"/></g>
<path d="M0 790 Q900 670 1800 790 V1040 H0Z" fill="url(#floor)"/>
<ellipse cx="1080" cy="850" rx="610" ry="120" fill="{accent}" opacity=".2" filter="url(#blur)"/>
<ellipse cx="1080" cy="850" rx="430" ry="48" fill="none" stroke="{accent}" stroke-width="5" opacity=".72" filter="url(#neon)"/>
<ellipse cx="1080" cy="850" rx="350" ry="32" fill="none" stroke="#8d6cff" stroke-width="3" opacity=".75"/>
<path d="M580 850 L760 755 H1420 L1590 850 L1420 925 H760Z" fill="url(#platform)" stroke="url(#rim)" stroke-width="4" opacity=".98"/>
<path d="M690 920 L810 865 H1370 L1480 920 L1370 975 H810Z" fill="#080c1c" stroke="{accent}" stroke-opacity=".5" stroke-width="3"/>
<path d="M790 780 H1390" stroke="#ffffff" stroke-opacity=".18" stroke-width="3"/>
<image x="260" y="75" width="1280" height="760" preserveAspectRatio="xMidYMid meet" transform="rotate({args.rotation} 910 475)" xlink:href="{data_uri}" filter="url(#shadow)"/>
<g fill="{accent}" opacity=".9" filter="url(#neon)"><circle cx="330" cy="280" r="5"/><circle cx="1530" cy="250" r="4"/><circle cx="1480" cy="670" r="6"/><circle cx="270" cy="690" r="3"/><circle cx="620" cy="170" r="3"/><circle cx="1160" cy="130" r="4"/><circle cx="1660" cy="520" r="3"/></g>
<g fill="#b8a3ff" opacity=".8"><circle cx="430" cy="520" r="2"/><circle cx="1440" cy="180" r="2"/><circle cx="1560" cy="760" r="2"/><circle cx="200" cy="450" r="2"/><circle cx="970" cy="220" r="2"/><circle cx="760" cy="640" r="2"/></g>
</svg>'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding='utf-8')
    print(f'Wrote {args.output} (source bytes embedded unchanged)')

if __name__ == '__main__':
    main()
