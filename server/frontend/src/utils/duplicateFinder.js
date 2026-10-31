export function albumToDuplicateAlbum(a) {
  return {
    id: a.id, title: a.title, artist: a.artist, year: a.year ?? 0,
    genre: a.genre, image_url: a.image_url, image_path: a.image_path,
    added_at: a.added_at, album_type: a.album_type, popularity: a.popularity,
    spotify_url: a.spotify_url,
  };
}

const bracketRegex = /[\(\[\{][^\)\]\}]*[\)\]\}]/g;
const suffixSplit = /\s+[-–—]\s+/g;
const combiningMarks = /\p{M}+/gu;
const nonAlnum = /[^a-z0-9]+/g;
const featSplit = /\s+(?:feat\.?|featuring|ft\.?)\s+/i;
const variantWords = ['deluxe', 'expanded', 'edition', 'remaster', 'remastered', 'reissue', 'bonus', 'anniversary', 'special', 'collector', 'collectors', 'limited', 'version', 'explicit', 'clean', 'mono', 'stereo', 'digipak'];
const regionTags = new Set(['uk', 'us', 'usa', 'eu', 'europe', 'european', 'international', 'japan', 'japanese', 'worldwide']);
const removablePhrases = [
  'deluxe edition', 'deluxe version', 'deluxe', 'expanded edition', 'expanded',
  "special edition", "collector's edition", "collectors edition", 'limited edition',
  'anniversary edition', 'remastered edition', 'remastered', 'remaster', 'reissue',
  'bonus track version', 'bonus tracks', 'bonus disc', 'explicit version',
  'clean version', 'international version', 'japanese edition', 'uk version', 'us version',
  'digipak',
];
const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function isVariantTag(text) {
  const t = text.toLowerCase().replace(nonAlnum, ' ').trim();
  if (t === '') return true;
  if (regionTags.has(t)) return true;
  return variantWords.some((word) => new RegExp('\\b' + word + '\\b', 'i').test(t));
}

export function normalizeTitle(raw) {
  let s = String(raw ?? '').toLowerCase().normalize('NFD').replace(combiningMarks, '');
  s = s.replace(/&/g, ' and ');
  s = s.replace(bracketRegex, (match) => {
    const inner = match.slice(1, -1).trim();
    return isVariantTag(inner) ? ' ' : ' ' + inner + ' ';
  });
  const parts = s.split(suffixSplit);
  if (parts.length > 1 && isVariantTag(parts[parts.length - 1])) {
    s = parts.slice(0, -1).join(' ');
  }
  for (const phrase of removablePhrases) {
    s = s.replace(new RegExp('\\b' + escapeRegex(phrase) + '\\b', 'gi'), ' ');
  }
  s = s.replace(nonAlnum, ' ').replace(/\s+/g, ' ').trim();
  if (s.startsWith('the ')) s = s.slice(4).trim();
  return s;
}

export function primaryArtist(raw) {
  let s = String(raw ?? '').toLowerCase().normalize('NFD').replace(combiningMarks, '');
  s = s.split(featSplit)[0] ?? s;
  s = s.split(',')[0] ?? s;
  s = s.replace(nonAlnum, ' ').replace(/\s+/g, ' ').trim();
  if (s.startsWith('the ')) s = s.slice(4).trim();
  return s;
}

export function findDuplicates(albums) {
  const buckets = new Map();
  for (const album of albums || []) {
    const a = album.id ? album : albumToDuplicateAlbum(album);
    const title = normalizeTitle(a.title);
    const artist = primaryArtist(a.artist);
    if (!title || !artist) continue;
    const key = title + '|' + artist;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(a);
  }
  const groups = [];
  for (const [key, list] of buckets) {
    if (list.length < 2) continue;
    const sorted = [...list].sort((a, b) => {
      const ay = a.year > 0 ? a.year : Number.MAX_SAFE_INTEGER;
      const by = b.year > 0 ? b.year : Number.MAX_SAFE_INTEGER;
      if (ay !== by) return ay - by;
      if (a.title.toLowerCase() !== b.title.toLowerCase()) {
        return a.title.toLowerCase().localeCompare(b.title.toLowerCase());
      }
      return String(a.id).localeCompare(String(b.id));
    });
    groups.push({ key, title: sorted[0].title, artist: sorted[0].artist, albums: sorted });
  }
  groups.sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()));
  return groups;
}
