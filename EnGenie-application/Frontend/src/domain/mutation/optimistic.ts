// Common shape behind ReviewScreen's handleReview / handleBulkAccept / commitEdit:
// apply a local state change immediately, then fire the backend call; if it
// rejects, let the caller decide how to react (full revert, snapshot revert,
// or just logging — these differ per call site and are NOT unified here).
export async function optimisticUpdate(params: {
  apply: () => void
  commit: () => Promise<unknown>
  onError: (err: unknown) => void
  onSettled?: () => void
}): Promise<void> {
  params.apply()
  try {
    await params.commit()
  } catch (err) {
    params.onError(err)
  } finally {
    params.onSettled?.()
  }
}
