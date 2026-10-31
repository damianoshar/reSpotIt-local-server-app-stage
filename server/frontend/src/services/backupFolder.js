const DB_NAME = 'reSpotIt_backup_folder'
const STORE = 'handles'
const KEY = 'directory'

function openDb() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB is unavailable.'))
      return
    }
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error || new Error('Could not open the backup-folder store.'))
  })
}

async function getHandle() {
  try {
    const db = await openDb()
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).get(KEY)
      req.onsuccess = () => resolve(req.result || null)
      req.onerror = () => reject(req.error || new Error('Could not read the backup folder.'))
    })
  } catch {
    return null
  }
}

async function putHandle(handle) {
  const db = await openDb()
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    const req = tx.objectStore(STORE).put(handle, KEY)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error || new Error('Could not store the backup folder.'))
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error || new Error('Could not store the backup folder.'))
  })
}

async function deleteHandle() {
  try {
    const db = await openDb()
    await new Promise((resolve) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).delete(KEY)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    })
  } catch {
    // ignore
  }
}

export function backupFolderSupported() {
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function'
}

export async function getBackupFolderName() {
  const handle = await getHandle()
  return handle?.name || ''
}

export async function chooseBackupFolder() {
  if (!backupFolderSupported()) throw new Error('This browser cannot choose a backup folder.')
  const handle = await window.showDirectoryPicker({ mode: 'readwrite' })
  const permission = await handle.queryPermission({ mode: 'readwrite' })
  if (permission !== 'granted') {
    const requested = await handle.requestPermission({ mode: 'readwrite' })
    if (requested !== 'granted') throw new Error('Backup folder permission was not granted.')
  }
  await putHandle(handle)
  return handle.name
}

export async function clearBackupFolder() {
  await deleteHandle()
}

export async function saveBackupToFolder(blob, filename) {
  const handle = await getHandle()
  if (!handle) return false
  let permission = await handle.queryPermission({ mode: 'readwrite' })
  if (permission !== 'granted') {
    try {
      permission = await handle.requestPermission({ mode: 'readwrite' })
    } catch {
      return false
    }
  }
  if (permission !== 'granted') return false
  try {
    const fileHandle = await handle.getFileHandle(filename, { create: true })
    const writable = await fileHandle.createWritable()
    await writable.write(blob)
    await writable.close()
    return true
  } catch {
    return false
  }
}