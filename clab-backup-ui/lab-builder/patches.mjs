// Build-time patches to the pinned @containerlab/clab-ui package, applied in memory by build.mjs while
// esbuild loads the named dist chunks. The package on disk is never modified and is not forked: each
// patch is one exact text replacement with its reason, and the build fails loudly when an anchor is no
// longer found exactly once (an editor upgrade changed the code: re-read the reason, port or drop the
// patch, then update tests/test_lab_builder_ui.js, which checks the committed bundle for each outcome).
export const PATCHES = [
  // Items 3 and 4 of docs/ui-ux-changes-2: the image is written exactly as typed, the version is never
  // filled in by the editor. Upstream appends ":latest" to an image whose version is empty, reads an
  // untagged image as version "latest", offers ["latest"] for an unknown image and takes the first
  // offered version whenever the image changes.
  {
    file: /chunk-TEX73Q7H\.js$/, why: "an untagged image reads as an empty version, not as latest",
    find: '  return { base: fullImage, version: "latest" };\n}', replace: '  return { base: fullImage, version: "" };\n}',
  },
  {
    file: /chunk-TEX73Q7H\.js$/, why: "a template or node without an image starts with empty fields, not with the first known image and latest",
    find: '    return { base: defaultBase, version: "latest" };', replace: '    return { base: "", version: "" };',
  },
  {
    file: /chunk-TEX73Q7H\.js$/, why: "an empty version writes the image with no tag; nothing is appended",
    find: '  return base ? `${base}:${version || "latest"}` : "";', replace: '  return base ? version ? `${base}:${version}` : base : "";',
  },
  {
    file: /chunk-TEX73Q7H\.js$/, why: "no version is offered for an image the site does not know (so none is picked)",
    find: '    (baseImage) => versionsByImage.get(baseImage) ?? ["latest"],', replace: '    (baseImage) => versionsByImage.get(baseImage) ?? [],',
  },
  {
    file: /chunk-TEX73Q7H\.js$/, why: "a known image without a tag offers no version either (latest is never invented)",
    find: '  } else if (!versionsByImage.has(image)) {\n    versionsByImage.set(image, ["latest"]);\n  }', replace: '  } else if (!versionsByImage.has(image)) {\n    versionsByImage.set(image, []);\n  }',
  },
  {
    file: /chunk-WM5ZW3ZW\.js$/, why: "changing the image keeps the version as typed (empty stays empty); the known tags stay offered in the Version list",
    find: '      const versions = getVersionsForImage(newBase);\n      const newVersion = versions.length > 0 ? versions[0] : localVersion;', replace: '      const newVersion = localVersion;',
  },
];

// Apply every patch whose file matches; each anchor must occur exactly once.
export function applyPatches(path, text) {
  let out = text;
  for (const patch of PATCHES) {
    if (!patch.file.test(path)) continue;
    const count = out.split(patch.find).length - 1;
    if (count !== 1) throw new Error(`editor patch anchor found ${count} times in ${path} (expected once): ${patch.why}. The pinned editor changed; port or drop the patch in lab-builder/patches.mjs.`);
    out = out.replace(patch.find, patch.replace);
  }
  return out;
}
