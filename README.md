# Image Compressor & Converter: Bulk WebP, AVIF, JPEG, PNG & HEIC to JPG

[![Run on Apify](https://img.shields.io/badge/Run%20on-Apify-1f6feb?logo=apify)](https://apify.com/manageable_gully/image-compressor-converter) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Run it in the cloud with no setup:** [Image Compressor & Converter: WebP, AVIF, JPEG, PNG, HEIC on the Apify Store](https://apify.com/manageable_gully/image-compressor-converter).  
> Pay only per result, export to JSON/CSV/Excel, schedule runs and call it from the API.
<!-- Note: the Apify Store page goes live once the Actor is published. -->
<!-- AFFILIATE_LINK_PLACEHOLDER: replace the Apify links above with the affiliate link when available -->

**Compress and convert images in bulk**: shrink JPEG and PNG files, convert to **WebP** or **AVIF** for a faster website, turn iPhone **HEIC photos into JPG**, **resize** to a maximum width or height, hit a **target file size** (e.g. "under 200 KB") and **strip EXIF metadata including the GPS location** from photos. Paste image links (or upload a file), click Start, and get one result row per image with the old and new size, the savings in percent and a **direct download link**, plus an optional **ZIP of all images**. No API key, no software to install. **$1 per 1,000 images**, and failed images are free.

## What you can use it for
- **Faster websites and better Core Web Vitals:** convert product photos and blog images to WebP or AVIF and cut page weight by 70-95%.
- **E-commerce catalogs:** resize and compress thousands of Shopify, WooCommerce or marketplace product images in one run, with a white background for transparent PNGs.
- **Upload limits:** make every file fit a size limit (job portals, forms, CMS, email attachments) with the target file size option.
- **iPhone photos (HEIC) to JPG** for Windows, older apps and websites that don't accept HEIC.
- **Privacy:** remove the GPS location and camera data from photos before you publish or share them.
- **Animated GIF to WebP:** keep the animation at a fraction of the size.
- **Automation:** call it from n8n, Make, Zapier, your CMS or an AI agent after every upload.

## How to use it
1. Paste direct image links in **Image links** (one per line, or import a text/CSV file) or **upload an image**. Google Drive ("Anyone with the link") and Dropbox share links work.
2. Pick the **output format** (WebP, AVIF, JPEG, PNG or keep the original format) and the **quality** (80 is a good default).
3. Optional: set a **max width/height**, a **target max file size**, what **metadata** to remove, and whether you want a **ZIP**.
4. Click **Start**. Each image becomes one row in the results with a `downloadUrl`. The ZIP link is in the `OUTPUT` record and in the run log.

## Pricing
You pay **$0.001 per image** ($1 per 1,000), plus $0.0005 when a run starts. An image is any picture up to 25 megapixels, which covers every phone and most camera photos. Bigger images and animations count per started 25 megapixels (an animated GIF counts all its frames). **Images that fail, are refused or are skipped are free, and so is the ZIP.**

| Job | Images | Price |
|---|---|---|
| Try it on one photo | 1 | **$0.0015** |
| 100 product photos to WebP | 100 | **$0.10** |
| 1,000 blog images resized to 1600 px | 1,000 | **$1.00** |
| 10,000 catalog images to AVIF | 10,000 | **$10.00** |
| A 48 MP camera photo | 1 (2 x 25 MP) | **$0.002** |

That's half of what most comparable Store Actors charge ($2-$10 per 1,000), and unlike online compressor web apps there is no monthly plan, no 20-files-at-a-time limit and no manual uploading.

## Features
- **Formats in:** JPEG, PNG, WebP, AVIF, **HEIC/HEIF** (iPhone), GIF (incl. animated), TIFF, BMP. **Formats out:** WebP, AVIF, JPEG, PNG, or keep the original format.
- **Smart compression:** optimized progressive JPEG, WebP and AVIF at the quality you choose; optional lossless WebP/AVIF; optional **TinyPNG-style PNG color reduction** (256 colors with dithering, usually 50-80% smaller).
- **Target file size:** finds the highest quality that fits your limit and, if needed, scales the image down until it fits.
- **Resize** to a max width and/or height, keeping the aspect ratio. Images are never enlarged.
- **Metadata & privacy:** removes all EXIF/XMP metadata incl. **GPS location** by default, or only the GPS data, or nothing. The camera rotation is applied to the pixels first, so photos never end up sideways. The color profile (e.g. iPhone Display P3) is kept so colors stay right.
- **Transparency:** kept for WebP, AVIF and PNG; filled with your background color for JPEG.
- **Animations:** animated GIF/WebP/PNG stay animated in WebP, AVIF, GIF and PNG output.
- **Never worse:** if re-encoding would make an already optimized file bigger (same format and size, no metadata to remove), the original is returned instead.
- **Safe:** only the links you give are downloaded; web pages, private network addresses, SVG and PDF files are refused with a clear message. Max 50 MB and 100 megapixels per image, up to 5,000 images per run.
- **Budget safe:** before each image it checks your run's max cost and skips images that would exceed it (not charged).

## Input example
```json
{
  "imageUrls": [
    {"url": "https://upload.wikimedia.org/wikipedia/commons/5/5c/Kennedy_will_be_one_of_Eglinton_Crosstown_LRT_stations%2C_GPS_embedded%2C_taken_2013_04_25_%281%29.JPG"},
    {"url": "https://upload.wikimedia.org/wikipedia/commons/2/2c/Rotating_earth_%28large%29.gif"}
  ],
  "outputFormat": "webp",
  "quality": 80,
  "maxWidth": 2560,
  "stripMetadata": "all",
  "createZip": true
}
```

## Output example (one item per image)
A real result: a 14-megapixel public-domain photo with GPS data, converted to WebP at 2560 px wide. 5.4 MB became 160 KB.
```json
{
  "url": "https://upload.wikimedia.org/wikipedia/commons/5/5c/Kennedy_will_be_one_of_Eglinton_Crosstown_LRT_stations%2C_GPS_embedded%2C_taken_2013_04_25_%281%29.JPG",
  "position": 1,
  "megapixels": 14.0,
  "fileName": "Kennedy_will_be_one_of_Eglinton_Crosstown_LRT_stations-_GPS_embedded-_taken_2013.webp",
  "inputFormat": "jpeg",
  "outputFormat": "webp",
  "originalBytes": 5385216,
  "outputBytes": 159902,
  "savedBytes": 5225314,
  "savingsPercent": 97.0,
  "originalWidth": 4320,
  "originalHeight": 3240,
  "width": 2560,
  "height": 1920,
  "frames": 1,
  "quality": 80,
  "metadataRemoved": ["gps", "exif"],
  "gpsRemoved": true,
  "downloadUrl": "https://api.apify.com/v2/key-value-stores/<store-id>/records/Kennedy_will_be_one_of_Eglinton_Crosstown_LRT_stations-_GPS_embedded-_taken_2013.webp?signature=...",
  "processingSeconds": 0.86,
  "billedUnits": 1
}
```
In the same run, the 44-frame animated "Rotating earth" GIF went from 1.0 MB to 288 KB as an animated WebP (-71%), and a transparent PNG from 225 KB to 69 KB (-69%) with its transparency kept. The run summary (`OUTPUT` record):
```json
{"images": 7, "processed": 4, "failed": 3, "skipped": 0, "originalBytes": 6620522, "outputBytes": 520168,
 "savedBytes": 6100354, "savingsPercent": 92.1, "billedUnits": 4, "zipUrl": "https://api.apify.com/v2/key-value-stores/<store-id>/records/images.zip?signature=..."}
```
The 3 failed rows were a web page, a 404 link and a private network address. They each got a clear `error` message and were not charged.

## Use it from code, n8n or AI agents
Call it through the Apify API (`POST https://api.apify.com/v2/acts/manageable_gully~image-compressor-converter/run-sync-get-dataset-items`), the Apify Python/JavaScript clients, the Apify n8n/Make/Zapier integrations, or as a tool for AI agents through the Apify MCP server. Every `downloadUrl` is a direct link you can save to S3, Google Drive or your CMS.

## FAQ
**WebP or AVIF?** WebP works in every current browser and is fast to encode. AVIF is usually 10-30% smaller again at the same look, and is supported by all modern browsers. If you are not sure, use WebP.

**Which quality should I use?** 75-85 looks like the original for almost all photos. Use 60-70 for thumbnails. For AVIF the same number gives a similar look (it is mapped to AVIF's own scale).

**Will my images lose quality?** JPEG, WebP and AVIF are lossy, but at 80 the difference is not visible for normal viewing. Use lossless WebP/AVIF or PNG for pixel-perfect output.

**Do you keep my images?** Converted files are stored only in your own Apify run storage (your account's data retention applies). Nothing is sent to third-party services.

**Can it download all images from a web page?** No. It only processes the image links you give it. To collect the image links of your own site, run [Broken Link Checker](https://apify.com/manageable_gully/broken-link-checker) with "include working links" on: it lists every image URL it checks.

**Can it convert SVG or PDF?** No. For PDFs and scanned images to text use [PDF & Image OCR Extractor](https://apify.com/manageable_gully/pdf-ocr-extractor).

**How big can images be?** Up to 50 MB and 100 megapixels per image (raise `maxMegapixels` to 150 and give the run 2 GB of memory for huge panoramas), up to 5,000 images per run.

## More tools from WebIntel Tools
- [Website Screenshot & URL to PDF](https://apify.com/manageable_gully/url-to-pdf-screenshot)
- [PDF & Image OCR to Text/Markdown](https://apify.com/manageable_gully/pdf-ocr-extractor)
- [Lighthouse & PageSpeed Bulk Audit](https://apify.com/manageable_gully/lighthouse-bulk-audit)
- [Broken Link Checker](https://apify.com/manageable_gully/broken-link-checker)
- [Web Page to Markdown for LLMs](https://apify.com/manageable_gully/page-to-markdown)

## Run from source
This repository is the full source of the [Image Compressor & Converter: WebP, AVIF, JPEG, PNG, HEIC](https://apify.com/manageable_gully/image-compressor-converter) Actor.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest
# run locally with the Apify CLI (https://docs.apify.com/cli):
apify run --input '{...}'
```

Deploy your own copy with `apify push`. The easiest way to use it is the hosted version on the [Apify Store](https://apify.com/manageable_gully/image-compressor-converter).

<!-- AFFILIATE_LINK_PLACEHOLDER: "New to Apify? Sign up here" link goes here -->

## License
MIT, see [LICENSE](LICENSE).
