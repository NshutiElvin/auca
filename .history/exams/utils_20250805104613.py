import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

shared_key = "zi04hD8XCSjoaK50qPhGUMfFJ62ixG6YVpdIzm8Z7K0"

def decrypt_message(encrypted_text, base64_key):
    key = base64.urlsafe_b64decode(base64_key + '==')
    data = base64.urlsafe_b64decode(encrypted_text + '==')
    nonce, ciphertext = data[:12], data[12:]

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()

if __name__ == "__main__":
    encrypted = input("Paste encrypted text: ")
    print("Decrypted:", decrypt_message(encrypted, shared_key))
