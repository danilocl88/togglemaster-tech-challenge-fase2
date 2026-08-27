package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/aws/aws-sdk-go/aws"
	"github.com/aws/aws-sdk-go/aws/session"
	"github.com/aws/aws-sdk-go/service/sqs"
	"github.com/go-redis/redis/v8"
	"github.com/joho/godotenv"
)

var ctx = context.Background()

type App struct {
	RedisClient         *redis.Client
	SqsSvc              *sqs.SQS
	SqsQueueURL         string
	HttpClient          *http.Client
	FlagServiceURL      string
	TargetingServiceURL string
	ServiceAPIKey       string
}

func main() {
	_ = godotenv.Load()

	port := envOrDefault("PORT", "8004")
	redisURL := os.Getenv("REDIS_URL")
	flagSvcURL := os.Getenv("FLAG_SERVICE_URL")
	targetingSvcURL := os.Getenv("TARGETING_SERVICE_URL")
	serviceAPIKey := os.Getenv("SERVICE_API_KEY")

	if redisURL == "" {
		log.Fatal("REDIS_URL deve ser definida")
	}
	if flagSvcURL == "" {
		log.Fatal("FLAG_SERVICE_URL deve ser definida")
	}
	if targetingSvcURL == "" {
		log.Fatal("TARGETING_SERVICE_URL deve ser definida")
	}
	if serviceAPIKey == "" {
		log.Fatal("SERVICE_API_KEY deve ser definida")
	}

	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Fatalf("Nao foi possivel interpretar REDIS_URL: %v", err)
	}
	rdb := redis.NewClient(opt)
	defer rdb.Close()
	if _, err := rdb.Ping(ctx).Result(); err != nil {
		log.Fatalf("Nao foi possivel conectar ao Redis: %v", err)
	}
	log.Println("Conectado ao Redis com sucesso!")

	sqsQueueURL := os.Getenv("AWS_SQS_URL")
	awsRegion := os.Getenv("AWS_REGION")
	if awsRegion == "" {
		awsRegion = os.Getenv("AWS_DEFAULT_REGION")
	}

	var sqsSvc *sqs.SQS
	if sqsQueueURL == "" {
		log.Println("AWS_SQS_URL nao definida. Publicacao de eventos SQS desabilitada neste ambiente.")
	} else {
		if awsRegion == "" {
			log.Fatal("AWS_REGION ou AWS_DEFAULT_REGION deve ser definida para usar SQS")
		}
		sess, err := session.NewSession(&aws.Config{Region: aws.String(awsRegion)})
		if err != nil {
			log.Fatalf("Nao foi possivel criar sessao AWS: %v", err)
		}
		sqsSvc = sqs.New(sess)
		log.Println("Cliente SQS inicializado com sucesso.")
	}

	app := &App{
		RedisClient:         rdb,
		SqsSvc:              sqsSvc,
		SqsQueueURL:         sqsQueueURL,
		HttpClient:          &http.Client{Timeout: 5 * time.Second},
		FlagServiceURL:      flagSvcURL,
		TargetingServiceURL: targetingSvcURL,
		ServiceAPIKey:       serviceAPIKey,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", app.healthHandler)
	mux.HandleFunc("/evaluate", app.evaluationHandler)
	// Alias da raiz para compatibilidade com o rewrite do Ingress (/evaluate -> /).
	mux.HandleFunc("/", app.rootEvaluationHandler)

	log.Printf("Servico de Avaliacao (Go) rodando na porta %s", port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}

func envOrDefault(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
