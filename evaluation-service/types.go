package main

import "fmt"

type Flag struct {
	ID          int    `json:"id"`
	Name        string `json:"name"`
	Description string `json:"description"`
	IsEnabled   bool   `json:"is_enabled"`
}

type TargetingRule struct {
	ID        int    `json:"id"`
	FlagName  string `json:"flag_name"`
	IsEnabled bool   `json:"is_enabled"`
	Rules     Rule   `json:"rules"`
}

type Rule struct {
	Type  string      `json:"type"`
	Value interface{} `json:"value"`
}

type CombinedFlagInfo struct {
	Flag *Flag          `json:"flag"`
	Rule *TargetingRule `json:"rule,omitempty"`
}

type NotFoundError struct {
	FlagName string
}

func (e *NotFoundError) Error() string {
	return fmt.Sprintf("flag ou regra '%s' nao encontrada", e.FlagName)
}
