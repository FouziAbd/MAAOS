"""`kit` — default implementations for domain authors (DK2 fills this package).

Reserved in DK1 so the lint/type/guard scopes name it once. Rules it will follow: imports
only stdlib and `shared`; extracted from what BoxPush and the R5 probe both implement by
hand; no domain vocabulary; only `kit/environment.py` may raise an `InfrastructureFault`.
"""
