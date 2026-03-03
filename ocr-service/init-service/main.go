package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

var (
	buckets = []string{
		"uploads",
		"extracted-text",
		"tmp-files",
		"tmp-extracted-text",
	}

	queues = []string{
		"file-processing",
		"ocr-processing",
		"ocr-complete",
	}
)

func main() {
	log.Println("============================================")
	log.Println("  LocalStack Resource Init Service")
	log.Println("============================================")

	endpoint := os.Getenv("LOCALSTACK_ENDPOINT")
	region := os.Getenv("AWS_REGION")
	if endpoint == "" {
		endpoint = "http://localstack:4566"
	}
	if region == "" {
		region = "us-east-1"
	}

	log.Printf("Endpoint: %s  Region: %s", endpoint, region)

	customResolver := aws.EndpointResolverWithOptionsFunc(
		func(service, reg string, options ...interface{}) (aws.Endpoint, error) {
			return aws.Endpoint{
				URL:               endpoint,
				HostnameImmutable: true,
			}, nil
		},
	)

	cfg, err := config.LoadDefaultConfig(context.TODO(),
		config.WithRegion(region),
		config.WithEndpointResolverWithOptions(customResolver),
	)
	if err != nil {
		log.Fatalf("FATAL: Failed to load AWS config: %v", err)
	}

	s3Client := s3.NewFromConfig(cfg, func(o *s3.Options) {
		o.UsePathStyle = true
	})
	sqsClient := sqs.NewFromConfig(cfg)

	ctx := context.TODO()

	// ── Wait for LocalStack to be ready ──────────────────────────────
	log.Println("")
	log.Println("--- Waiting for LocalStack ---")
	if !waitForLocalStack(ctx, s3Client, sqsClient) {
		log.Fatal("FATAL: LocalStack did not become ready in time")
	}

	// ── Create S3 Buckets ────────────────────────────────────────────
	log.Println("")
	log.Println("--- Creating S3 Buckets ---")
	for _, bucket := range buckets {
		createBucket(ctx, s3Client, bucket)
	}

	// ── Create SQS Queues ────────────────────────────────────────────
	log.Println("")
	log.Println("--- Creating SQS Queues ---")
	for _, queue := range queues {
		createQueue(ctx, sqsClient, queue)
	}

	// ── Verify Everything ────────────────────────────────────────────
	log.Println("")
	log.Println("--- Verifying Resources ---")
	allOK := true

	log.Println("S3 Buckets:")
	listResult, err := s3Client.ListBuckets(ctx, &s3.ListBucketsInput{})
	if err != nil {
		log.Printf("  ERROR listing buckets: %v", err)
		allOK = false
	} else {
		for _, b := range listResult.Buckets {
			log.Printf("  ✓ %s", *b.Name)
		}
		if len(listResult.Buckets) < len(buckets) {
			log.Printf("  WARNING: Expected %d buckets, found %d", len(buckets), len(listResult.Buckets))
			allOK = false
		}
	}

	log.Println("SQS Queues:")
	queueResult, err := sqsClient.ListQueues(ctx, &sqs.ListQueuesInput{})
	if err != nil {
		log.Printf("  ERROR listing queues: %v", err)
		allOK = false
	} else {
		for _, url := range queueResult.QueueUrls {
			log.Printf("  ✓ %s", url)
		}
		if len(queueResult.QueueUrls) < len(queues) {
			log.Printf("  WARNING: Expected %d queues, found %d", len(queues), len(queueResult.QueueUrls))
			allOK = false
		}
	}

	log.Println("")
	if allOK {
		log.Println("============================================")
		log.Println("  All resources created and verified!")
		log.Println("============================================")
	} else {
		log.Println("============================================")
		log.Println("  WARNING: Some resources may be missing!")
		log.Println("============================================")
		os.Exit(1)
	}
}

// waitForLocalStack polls until both S3 and SQS respond.
func waitForLocalStack(ctx context.Context, s3Client *s3.Client, sqsClient *sqs.Client) bool {
	for i := 0; i < 60; i++ {
		_, s3Err := s3Client.ListBuckets(ctx, &s3.ListBucketsInput{})
		_, sqsErr := sqsClient.ListQueues(ctx, &sqs.ListQueuesInput{})

		if s3Err == nil && sqsErr == nil {
			log.Println("LocalStack S3 and SQS are ready!")
			return true
		}

		if i%5 == 0 {
			log.Printf("  [%d/60] Waiting for LocalStack... s3=%v sqs=%v", i+1, s3Err, sqsErr)
		}
		time.Sleep(2 * time.Second)
	}
	return false
}

func createBucket(ctx context.Context, client *s3.Client, name string) {
	// Check if already exists
	_, err := client.HeadBucket(ctx, &s3.HeadBucketInput{
		Bucket: aws.String(name),
	})
	if err == nil {
		log.Printf("  Bucket '%s' already exists, skipping", name)
		return
	}

	// Create bucket
	_, err = client.CreateBucket(ctx, &s3.CreateBucketInput{
		Bucket: aws.String(name),
		CreateBucketConfiguration: &s3types.CreateBucketConfiguration{
			LocationConstraint: s3types.BucketLocationConstraintUsEast2,
		},
	})
	// LocalStack sometimes ignores LocationConstraint, try without it
	if err != nil {
		_, err = client.CreateBucket(ctx, &s3.CreateBucketInput{
			Bucket: aws.String(name),
		})
	}
	if err != nil {
		log.Printf("  ERROR creating bucket '%s': %v", name, err)
		return
	}

	// Wait for bucket to exist
	for j := 0; j < 10; j++ {
		_, err := client.HeadBucket(ctx, &s3.HeadBucketInput{
			Bucket: aws.String(name),
		})
		if err == nil {
			log.Printf("  Created bucket: %s", name)
			return
		}
		time.Sleep(500 * time.Millisecond)
	}
	log.Printf("  Created bucket '%s' (unconfirmed)", name)
}

func createQueue(ctx context.Context, client *sqs.Client, name string) {
	// Check if already exists
	existing, err := client.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(name),
	})
	if err == nil && existing.QueueUrl != nil {
		log.Printf("  Queue '%s' already exists: %s", name, *existing.QueueUrl)
		return
	}

	// Create queue with attributes
	result, err := client.CreateQueue(ctx, &sqs.CreateQueueInput{
		QueueName: aws.String(name),
		Attributes: map[string]string{
			"VisibilityTimeout":   "300",
			"MessageRetentionPeriod": "86400",
			"ReceiveMessageWaitTimeSeconds": "20",
		},
	})
	if err != nil {
		log.Printf("  ERROR creating queue '%s': %v", name, err)
		return
	}

	log.Printf("  Created queue: %s -> %s", name, *result.QueueUrl)

	// Verify queue is accessible
	for j := 0; j < 10; j++ {
		_, err := client.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
			QueueName: aws.String(name),
		})
		if err == nil {
			return
		}
		time.Sleep(500 * time.Millisecond)
	}
	fmt.Printf("  Queue '%s' created (unconfirmed)\n", name)
}
