variable "subscription_id" {
  description = "Azure subscription to deploy into"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus2"
}

variable "prefix" {
  description = "Short lowercase prefix for resource names (storage accounts need globally unique names)"
  type        = string
  default     = "invflow"
}
