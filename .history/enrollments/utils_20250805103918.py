import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
 

def decrypt_message(encrypted_text, base64_key):
    key = base64.urlsafe_b64decode(base64_key + '==')
    data = base64.urlsafe_b64decode(encrypted_text + '==')
    nonce, ciphertext = data[:12], data[12:]

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()

 
