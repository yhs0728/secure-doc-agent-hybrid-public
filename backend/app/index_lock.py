from threading import RLock

# This protects writes in the current process. Multi-process deployments need
# a file lock or a distributed lock instead.
index_lock = RLock()
