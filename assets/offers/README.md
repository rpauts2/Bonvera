# BONVERA offer image system

## Visual target

Every offer image must look like a premium BONVERA campaign tile, not a flat logo card:

- 16:9 landscape master, 1800×1040 px (or larger, same ratio).
- Deep navy / violet environment, restrained cyan accents, warm gold rim light.
- Real product render is the hero: actual issued bank card, official brand mark, or the real service/product mark.
- Dramatic but controlled studio lighting, perspective, realistic contact shadow, soft reflections and depth.
- Keep a safe text-free zone: the application renders reward, name and conditions as UI, not baked into the image.
- Do not place numbers, cardholder names, expiry dates, CVV, fake chip details, payment marks or features that are not present in the verified source image.

## Asset truth rules

1. Bank cards: use the exact official card product visual for the offer's named product. Do not substitute another bank's card or an unrelated design from the same bank.
2. Expired/discontinued products: mark as discontinued / verify with the partner. Do not use a current unrelated card as a replacement.
3. MFO and CPL: use the real provider's approved logo/product imagery; never use a fabricated bank card as a category illustration.
4. If no verified source exists, use a clearly branded abstract provider tile without pretending it is a physical card.
5. Keep source URL, retrieval date, checksum, and permission status in `docs/offer-image-asset-register.csv` before publishing the asset.
6. Do not hotlink partner images in production. Store optimized local copies only after usage rights are confirmed.

## Current state

The 93 JPG files in this directory are legacy generated placeholders. Their paths are referenced by the catalog and bot. They must remain in place until each replacement is verified and regression-tested. The current artwork is not an approved source of truth for real card designs.

## Replacement workflow

1. Verify exact offer product name and whether the product is currently issued.
2. Find the official bank/provider page or an approved partner media kit.
3. Confirm image usage rights for BONVERA's commercial affiliate placement.
4. Save the original source file in a temporary review folder; never overwrite the live JPG before approval.
5. Composite the authentic product into the BONVERA visual stage while preserving every visible product detail.
6. Export JPG/WebP at 1800×1040 or larger, optimize, and inspect at 360 px mobile width.
7. Update the CSV source, rights and checksum fields; run the asset validation script and frontend tests.

## Verified official product reference pages (source discovery, not reuse permission)

- T-Bank Black: https://www.tbank.ru/cards/debit-cards/tinkoff-black/
- Alfa-Card: https://alfabank.ru/everyday/debit-cards/alfacard/
- Ozon Bank card: https://finance.ozon.ru/promo/cards
- Sovcombank Halva: https://sovcombank.ru/cards/debit/karta-halva
- OTP Card: https://www.otpbank.ru/retail/cards/debit/otpcard/
- Bank Saint Petersburg debit cards: https://www.bspb.ru/retail/cards/debit
- UBRIR bank cards: https://www.ubrr.ru/chastnym-klientam/bankovskie-karty
- VTB digital card designs: https://www.vtb.ru/personal/karty/debetovye/digital-designs/
- Ak Bars debit cards: https://www.akbars.ru/individuals/cards/
- Fora Bank card application: https://card.forabank.ru/
- MTS Money card support: https://support.mts.ru/karti_mts_dengi/oformlenie-perevipusk-i-zakritie-karti/kak-oformit-debetovuyu-kartu

The register intentionally does not mark these sources as licensed. Public availability does not grant commercial reuse permission.
