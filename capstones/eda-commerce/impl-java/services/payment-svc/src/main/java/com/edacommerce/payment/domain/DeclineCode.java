package com.edacommerce.payment.domain;

/** Our decline vocabulary (anti-corruption layer: PSP failure codes never leave the adapter). */
public enum DeclineCode {
  INSUFFICIENT_FUNDS,
  CARD_DECLINED,
  FRAUD_SUSPECTED,
  PSP_TIMEOUT,
  PSP_ERROR
}
