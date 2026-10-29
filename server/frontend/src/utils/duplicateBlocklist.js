const IDS_KEY = 'reSpotIt_duplicate_hidden_ids';
const ALBUMS_KEY = 'reSpotIt_duplicate_hidden_albums';

export function getHiddenDuplicateIds() {
  try { return new Set(JSON.parse(localStorage.getItem(IDS_KEY) || '[]')); } catch { return new Set(); }
}

export function getHiddenDuplicateAlbums() {
  try { return JSON.parse(localStorage.getItem(ALBUMS_KEY) || '[]'); } catch { return []; }
}

export function hideDuplicates(albums) {
  const ids = getHiddenDuplicateIds();
  const cached = getHiddenDuplicateAlbums();
  const byId = new Map(cached.map((a) => [a.id, a]));
  for (const album of albums) {
    ids.add(album.id);
    byId.set(album.id, album);
  }
  localStorage.setItem(IDS_KEY, JSON.stringify([...ids]));
  localStorage.setItem(ALBUMS_KEY, JSON.stringify([...byId.values()]));
}

export function restoreHiddenDuplicates() {
  localStorage.removeItem(IDS_KEY);
  localStorage.removeItem(ALBUMS_KEY);
  return getHiddenDuplicateAlbums();
}

export function hideDuplicateIds(ids = []) {
  const hidden = getHiddenDuplicateIds();
  for (const id of ids) hidden.add(id);
  try { localStorage.setItem(IDS_KEY, JSON.stringify([...hidden])) } catch {}
}

export function useDuplicateBlocklist() {
  return { getHiddenDuplicateIds, getHiddenDuplicateAlbums, hideDuplicates, restoreHiddenDuplicates };
}
