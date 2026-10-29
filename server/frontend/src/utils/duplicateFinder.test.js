import { describe, it, expect } from 'vitest'
import { findDuplicates, normalizeTitle, primaryArtist } from './duplicateFinder'

describe('duplicateFinder', () => {
  it('normalises variant and region tags', () => {
    expect(normalizeTitle('OK Computer (Deluxe Edition)')).toBe(normalizeTitle('OK Computer - Remastered'))
  })

  it('groups deluxe/regional duplicates by normalised title and artist', () => {
    const albums = [
      { id: '1', title: 'Album', artist: 'Artist', year: 2020 },
      { id: '2', title: 'Album (Deluxe Edition)', artist: 'Artist', year: 2021 },
      { id: '3', title: 'Other', artist: 'Artist Two', year: 2022 },
    ]
    const groups = findDuplicates(albums)
    expect(groups).toHaveLength(1)
    expect(groups[0].albums.map((a) => a.id)).toEqual(['1', '2'])
  })

  it('keeps (Live) and (Acoustic) distinct', () => {
    expect(normalizeTitle('Song (Live)')).not.toBe(normalizeTitle('Song (Acoustic)'))
  })

  it('extracts primary artist before feat/comma', () => {
    expect(primaryArtist('Artist, feat. Guest')).toBe('artist')
  })
})
