/* Plain-language text for what the tools log (both pages). The raw lines stay in the Details log; the page shows these. */
window.LA_FRIENDLY = (() => {
  'use strict';
  // quality-gate reasons (atlas_quality.verdict): [pattern, short title, explanation]
  const QUALITY = [
    [/^overexposed/, 'Overexposed', 'A large part of the Moon is clipped to pure white, so the craters there have no detail left to match.'],
    [/^too blurry/, 'Too blurry', 'The edge of the Moon is soft, so small craters cannot be placed reliably. Seeing, focus or a long exposure can cause this.'],
    [/^over-sharpened/, 'Over-sharpened', 'A bright and dark halo around the edge shows heavy sharpening, which creates detail that is not on the Moon.'],
    [/^too noisy/, 'Too noisy', 'Grain in the smooth seas hides the fine detail used to match the photo. Stacking more frames helps.'],
    [/^heavy JPEG/, 'Heavy JPEG compression', 'Blocky compression artefacts hide fine detail. Use the original, or save it as TIFF or PNG.'],
    [/^colour boosted/, 'Colours boosted', 'The colour saturation is far beyond the Moon’s own, which disturbs the brightness the matching relies on.'],
    [/^colour fringes/, 'Colour fringes', 'The red and blue edges of the Moon do not line up (atmospheric dispersion or chromatic aberration).'],
    [/^posterised/, 'Posterised', 'Many grey levels are missing, usually from a strong stretch of an 8-bit image.'],
    [/^too little fine detail/, 'Too little fine detail', 'The photo looks soft or enlarged, so there is too little small-scale detail to match.'],
  ];
  function quality(reason) {
    for (const [re, title, text] of QUALITY) if (re.test(reason)) return { title, text, raw: reason };
    return { title: 'Quality', text: reason, raw: reason };
  }
  // 'quality refused: a; b · measures' (the gate's line) -> [{title, text, raw}]
  function gate(line) {
    const m = /^quality refused:\s*(.*?)(?:\s+·\s|$)/.exec(line || '');
    return m ? m[1].split(/;\s*/).filter(Boolean).map(quality) : [];
  }
  // one log line -> a sentence for the page, or null (then the stage name says enough)
  const LINES = [
    [/optics unknown/, 'Camera and telescope are not set up, so every known setup is tried. This takes a little longer.'],
    [/optics not given/, 'Camera and telescope are not set up, so every known setup is tried.'],
    [/downloading the LOLA elevation model, 64/, 'Downloading the detailed elevation map for close-ups (about 530 MB, once).'],
    [/downloading the LOLA elevation model/, 'Downloading the Moon’s elevation map (about 33 MB, once).'],
    [/downloading reference tile/, 'Downloading the Moon map (4 parts of about 22 MB, once).'],
    [/downloading the IAU nomenclature/, 'Downloading the official list of names (about 24 MB, once).'],
    [/downloading font/, 'Downloading a font (once).'],
    [/searching the image as a close-up/, 'The edge of the Moon is not in the photo: searching it as a close-up.'],
    // only a close-up takes its tilt from the time; a photo with the limb fits it (its 'disk … libration' lines)
    [/^capture .*libration/, 'Using the capture time to work out the Moon’s tilt (libration).'],
    [/^\s*disk \d+ px: \d+ matches/, 'Refining the fit on a larger copy of the photo.'],
    [/^limb:/, 'Found the edge of the Moon.'],
    [/^orientation:/, 'Worked out which way is north.'],
    [/matching against the albedo map only/, 'No elevation map available: matching on brightness only.'],
    [/candidate scales/, 'Trying the likely image scales.'],
    [/close-up located|^result:/, 'Found where the photo is on the Moon.'],
    [/preparing the viewer/, 'Preparing the viewer. Large mosaics take a minute the first time.'],
    [/cancelled/, 'Cancelled.'],
  ];
  function line(l) {
    const t = String(l).trim();
    for (const [re, text] of LINES) if (re.test(t)) return text;
    return null;
  }
  // an error from the launcher -> {title, text, reasons}
  function error(msg, refused) {
    const m = String(msg || '').replace(/\.? ?Use --force to annotate anyway\.?/, '');
    if (refused || /^not annotated/.test(m)) {
      const reasons = m.replace(/^not annotated:\s*/, '').split(/;\s*/).filter(Boolean).map(quality);
      return { title: 'This photo did not pass the quality check', text: 'LunarAtlas can still try to name it, but the names may land in the wrong place.', reasons };
    }
    if (/close-up needs (its|the) capture time/.test(m))
      return { title: 'This looks like a close-up', text: 'A close-up needs the date and time it was taken, to work out the lighting. Choose the photo again and fill in when it was taken.', reasons: [], raw: m, needsTime: true };
    if (/no optics setup/.test(m))
      return { title: 'The camera and telescope could not be worked out', text: 'None of the known setups gives a close-up at this image size.', reasons: [], raw: m };
    if (/no Moon found|could not find the limb|no limb in view|too few terrain matches|close-up not found|not positioned/i.test(m))
      return { title: 'The Moon could not be found in this photo', text: 'Check that it is a photo of the Moon with enough detail. For a close-up, enter when it was taken.', reasons: [], raw: m };
    if (/cannot reach|urlopen|offline|timed out|Name or service/i.test(m))
      return { title: 'The Moon maps could not be downloaded', text: 'The first run needs an internet connection once. Check the connection and try again.', reasons: [], raw: m };
    return { title: 'That did not work', text: m.charAt(0).toUpperCase() + m.slice(1), reasons: [] };
  }
  return { quality, gate, line, error };
})();
