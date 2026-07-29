package crypto

import "testing"

const testKey = "0123456789abcdef0123456789abcdef"

func TestEncryptDecrypt(t *testing.T) {
	plaintext := "credential-secret-value"

	ciphertext, err := Encrypt(plaintext, testKey)
	if err != nil {
		t.Fatalf("Encrypt() error = %v", err)
	}

	decrypted, err := Decrypt(ciphertext, testKey)
	if err != nil {
		t.Fatalf("Decrypt() error = %v", err)
	}

	if decrypted != plaintext {
		t.Fatalf("Decrypt() = %q, want %q", decrypted, plaintext)
	}
}

func TestUniqueNonces(t *testing.T) {
	plaintext := "same plaintext"

	first, err := Encrypt(plaintext, testKey)
	if err != nil {
		t.Fatalf("first Encrypt() error = %v", err)
	}

	second, err := Encrypt(plaintext, testKey)
	if err != nil {
		t.Fatalf("second Encrypt() error = %v", err)
	}

	if first == second {
		t.Fatalf("Encrypt() returned identical ciphertexts for two encryptions")
	}
}
