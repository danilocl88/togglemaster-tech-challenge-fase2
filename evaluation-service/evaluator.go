package main

import (
	"crypto/sha1"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/go-redis/redis/v8"
)

const cacheTTL = 30 * time.Second

func (a *App) getDecision(userID, flagName string) (bool, error) {
	info, err := a.getCombinedFlagInfo(flagName)
	if err != nil {
		return false, err
	}
	return a.runEvaluationLogic(info, userID), nil
}

func (a *App) getCombinedFlagInfo(flagName string) (*CombinedFlagInfo, error) {
	cacheKey := fmt.Sprintf("flag_info:%s", flagName)

	val, err := a.RedisClient.Get(ctx, cacheKey).Result()
	if err == nil {
		var info CombinedFlagInfo
		if err := json.Unmarshal([]byte(val), &info); err == nil {
			log.Printf("Cache HIT para flag '%s'", flagName)
			return &info, nil
		}
		log.Printf("Cache invalido para flag '%s'; buscando origem", flagName)
	} else if !errors.Is(err, redis.Nil) {
		log.Printf("Falha de leitura no Redis para flag '%s': %v", flagName, err)
	}

	log.Printf("Cache MISS para flag '%s'", flagName)
	info, err := a.fetchFromServices(flagName)
	if err != nil {
		return nil, err
	}

	if jsonData, err := json.Marshal(info); err == nil {
		if err := a.RedisClient.Set(ctx, cacheKey, jsonData, cacheTTL).Err(); err != nil {
			log.Printf("Nao foi possivel gravar cache para flag '%s': %v", flagName, err)
		}
	}

	return info, nil
}

func (a *App) fetchFromServices(flagName string) (*CombinedFlagInfo, error) {
	var wg sync.WaitGroup
	wg.Add(2)

	var flagInfo *Flag
	var ruleInfo *TargetingRule
	var flagErr, ruleErr error

	go func() {
		defer wg.Done()
		flagInfo, flagErr = a.fetchFlag(flagName)
	}()

	go func() {
		defer wg.Done()
		ruleInfo, ruleErr = a.fetchRule(flagName)
	}()

	wg.Wait()

	if flagErr != nil {
		return nil, flagErr
	}

	if ruleErr != nil {
		var notFound *NotFoundError
		if errors.As(ruleErr, &notFound) {
			log.Printf("Nenhuma regra de segmentacao encontrada para '%s'. Usando comportamento padrao.", flagName)
			ruleInfo = nil
		} else {
			return nil, ruleErr
		}
	}

	return &CombinedFlagInfo{Flag: flagInfo, Rule: ruleInfo}, nil
}

func (a *App) fetchFlag(flagName string) (*Flag, error) {
	url := fmt.Sprintf("%s/flags/%s", a.FlagServiceURL, flagName)
	respBody, statusCode, err := a.doAuthenticatedGET(url)
	if err != nil {
		return nil, fmt.Errorf("erro ao chamar flag-service: %w", err)
	}
	if statusCode == http.StatusNotFound {
		return nil, &NotFoundError{FlagName: flagName}
	}
	if statusCode != http.StatusOK {
		return nil, fmt.Errorf("flag-service retornou status %d", statusCode)
	}

	var flag Flag
	if err := json.Unmarshal(respBody, &flag); err != nil {
		return nil, fmt.Errorf("erro ao desserializar resposta do flag-service: %w", err)
	}
	return &flag, nil
}

func (a *App) fetchRule(flagName string) (*TargetingRule, error) {
	url := fmt.Sprintf("%s/rules/%s", a.TargetingServiceURL, flagName)
	respBody, statusCode, err := a.doAuthenticatedGET(url)
	if err != nil {
		return nil, fmt.Errorf("erro ao chamar targeting-service: %w", err)
	}
	if statusCode == http.StatusNotFound {
		return nil, &NotFoundError{FlagName: flagName}
	}
	if statusCode != http.StatusOK {
		return nil, fmt.Errorf("targeting-service retornou status %d", statusCode)
	}

	var rule TargetingRule
	if err := json.Unmarshal(respBody, &rule); err != nil {
		return nil, fmt.Errorf("erro ao desserializar resposta do targeting-service: %w", err)
	}
	return &rule, nil
}

func (a *App) doAuthenticatedGET(url string) ([]byte, int, error) {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Authorization", "Bearer "+a.ServiceAPIKey)

	resp, err := a.HttpClient.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, resp.StatusCode, err
	}
	return body, resp.StatusCode, nil
}

func (a *App) runEvaluationLogic(info *CombinedFlagInfo, userID string) bool {
	if info == nil || info.Flag == nil || !info.Flag.IsEnabled {
		return false
	}

	if info.Rule == nil || !info.Rule.IsEnabled {
		return true
	}

	rule := info.Rule.Rules
	if rule.Type != "PERCENTAGE" {
		log.Printf("Tipo de regra '%s' nao suportado para a flag '%s'", rule.Type, info.Flag.Name)
		return false
	}

	percentage, ok := rule.Value.(float64)
	if !ok || percentage < 0 || percentage > 100 {
		log.Printf("Valor de porcentagem invalido para a flag '%s'", info.Flag.Name)
		return false
	}

	userBucket := getDeterministicBucket(userID + info.Flag.Name)
	return float64(userBucket) < percentage
}

func getDeterministicBucket(input string) int {
	hasher := sha1.New()
	_, _ = hasher.Write([]byte(input))
	hash := hasher.Sum(nil)
	val := binary.BigEndian.Uint32(hash[:4])
	return int(val % 100)
}
