package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strings"
)

type CreateKeyRequest struct {
	Name string `json:"name"`
}

type CreateKeyResponse struct {
	Name    string `json:"name"`
	Key     string `json:"key"`
	Message string `json:"message"`
}

func (a *App) healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func bearerToken(r *http.Request) string {
	authHeader := strings.TrimSpace(r.Header.Get("Authorization"))
	const prefix = "Bearer "
	if !strings.HasPrefix(authHeader, prefix) {
		return ""
	}
	return strings.TrimSpace(strings.TrimPrefix(authHeader, prefix))
}

func (a *App) validateKeyHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Metodo nao permitido", http.StatusMethodNotAllowed)
		return
	}

	keyString := bearerToken(r)
	if keyString == "" {
		http.Error(w, "Authorization Bearer obrigatorio", http.StatusUnauthorized)
		return
	}

	keyHash := hashAPIKey(keyString)
	var id int
	err := a.DB.QueryRow(
		"SELECT id FROM api_keys WHERE key_hash = $1 AND is_active = true",
		keyHash,
	).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		http.Error(w, "Chave de API invalida ou inativa", http.StatusUnauthorized)
		return
	}
	if err != nil {
		log.Printf("Erro de banco ao validar chave (hash: %s...): %v", keyHash[:6], err)
		http.Error(w, "Erro interno do servidor", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"message": "Chave valida"})
}

func (a *App) createKeyHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Metodo nao permitido", http.StatusMethodNotAllowed)
		return
	}

	var req CreateKeyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Corpo da requisicao invalido", http.StatusBadRequest)
		return
	}

	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		http.Error(w, "O campo 'name' e obrigatorio", http.StatusBadRequest)
		return
	}

	newKey, err := generateAPIKey()
	if err != nil {
		http.Error(w, "Erro ao gerar a chave", http.StatusInternalServerError)
		return
	}

	newKeyHash := hashAPIKey(newKey)
	var newID int
	if err := a.DB.QueryRow(
		"INSERT INTO api_keys (name, key_hash) VALUES ($1, $2) RETURNING id",
		req.Name,
		newKeyHash,
	).Scan(&newID); err != nil {
		log.Printf("Erro ao salvar a chave no banco: %v", err)
		http.Error(w, "Erro ao salvar a chave", http.StatusInternalServerError)
		return
	}

	log.Printf("Nova chave criada com sucesso (ID: %d, Name: %s)", newID, req.Name)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	_ = json.NewEncoder(w).Encode(CreateKeyResponse{
		Name:    req.Name,
		Key:     newKey,
		Message: "Guarde esta chave com seguranca! Voce nao podera ve-la novamente.",
	})
}

func (a *App) masterKeyAuthMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if bearerToken(r) != a.MasterKey {
			http.Error(w, "Acesso nao autorizado", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}
