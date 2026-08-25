# Cryptographic data lengths
# Raw hash size in bytes; produces 32 hexadecimal characters.
HASH_BYTES = 16

# Raw API-token size in bytes; produces 43 Base64URL characters without padding.
API_TOKEN_BYTES = 32

# Raw subscription-token size in bytes; produces 43 Base64URL characters without padding.
SUBSCRIPTION_TOKEN_BYTES = 32

# Length of UUID strings used for provider_hash and user_hash; fixed by UUID representation.
UUID_LENGTH = 36

# Length of hexadecimal source hashes; must not exceed the DB column size.
HASH_LENGTH = HASH_BYTES * 2

# Length of unpadded Base64URL token; must not exceed the DB column size.
API_TOKEN_LENGTH = (API_TOKEN_BYTES * 8 + 5) // 6

# Length of unpadded Base64URL token; must not exceed the DB column size.
SUBSCRIPTION_TOKEN_LENGTH = (SUBSCRIPTION_TOKEN_BYTES * 8 + 5) // 6


# Provider name limits
# Minimum provider_name length; must not exceed PROVIDER_NAME_MAX_LENGTH.
PROVIDER_NAME_MIN_LENGTH = 4

# Maximum provider_name length; must not exceed the DB column size.
PROVIDER_NAME_MAX_LENGTH = 16


# URL limits
# Maximum URL length; must not exceed the DB column size.
URL_MAX_LENGTH = 255


# User ID limits
# Minimum user ID; must not exceed USER_ID_MAX.
USER_ID_MIN = 1

# Maximum user ID; must not exceed the BIGINT maximum.
USER_ID_MAX = 999_999_999_999


# Comment limits
# Maximum config comment length; must not exceed the DB column size.
COMMENT_MAX_LENGTH = 255


# Subscription limits
# Maximum subscription name length; must not exceed the DB column size.
SUBSCRIPTION_NAME_MAX_LENGTH = 64

# Maximum subscription description length; must not exceed the DB column size.
SUBSCRIPTION_DESCRIPTION_MAX_LENGTH = 64

# Truncated HMAC length used in authorization links
AUTH_HMAC_LENGTH = 24
