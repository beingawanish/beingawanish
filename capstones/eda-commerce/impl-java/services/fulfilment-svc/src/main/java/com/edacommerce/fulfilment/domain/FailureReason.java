package com.edacommerce.fulfilment.domain;

/** Why the warehouse could not fulfil an order (FulfilmentFailed.reason). */
public enum FailureReason {
  STOCK_DAMAGED,
  STOCK_NOT_FOUND,
  ADDRESS_UNSERVICEABLE
}
