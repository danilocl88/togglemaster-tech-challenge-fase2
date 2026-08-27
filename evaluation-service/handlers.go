package main

import (
	"encoding/json"
	"log"
	"net/http"
)

type EvaluationResponse struct {
	FlagName string `json:"flag_name"`
	UserID   string `json:"user_id"`
	Result   bool   `json:"result"`
}

func (a *App) healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func (a *App) evaluationHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodGet {
		writeJSONError(w, "Metodo nao permitido", http.StatusMethodNotAllowed)
		return
	}

	userID := r.URL.Query().Get("user_id")
	flagName := r.URL.Query().Get("flag_name")
	if userID == "" || flagName == "" {
		writeJSONError(w, "user_id e flag_name sao obrigatorios", http.StatusBadRequest)
		return
	}

	result, err := a.getDecision(userID, flagName)
	if err != nil {
		if _, ok := err.(*NotFoundError); ok {
			result = false
		} else {
			log.Printf("Erro ao avaliar flag '%s': %v", flagName, err)
			writeJSONError(w, "Erro interno ao avaliar a flag", http.StatusBadGateway)
			return
		}
	}

	// A publicacao no SQS e assincrona e nao bloqueia a resposta ao cliente.
	go a.sendEvaluationEvent(userID, flagName, result)

	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(EvaluationResponse{
		FlagName: flagName,
		UserID:   userID,
		Result:   result,
	})
}

func (a *App) rootEvaluationHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	a.evaluationHandler(w, r)
}

func writeJSONError(w http.ResponseWriter, message string, status int) {
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}
