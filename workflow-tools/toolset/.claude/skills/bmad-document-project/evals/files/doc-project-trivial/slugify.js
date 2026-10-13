// slugify.js
// A single-purpose utility module. This is the entire project.
// Converts an arbitrary string into a URL-safe slug.
function slugify(input) {
  return String(input)
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

module.exports = slugify;
