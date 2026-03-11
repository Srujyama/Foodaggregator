import {
  collection,
  getDocs,
  query,
  orderBy,
  limit as firestoreLimit,
} from 'firebase/firestore'
import { db } from './client.js'

export async function getPopularSearches(limitCount = 8) {
  try {
    const q = query(
      collection(db, 'popular_searches'),
      orderBy('count', 'desc'),
      firestoreLimit(limitCount),
    )
    const snapshot = await getDocs(q)
    return snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }))
  } catch {
    return []
  }
}
