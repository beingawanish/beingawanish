package com.edacommerce.returns.domain;

/** Why the customer returns (ReturnRequested.reason). */
public enum ReturnReason {
  DAMAGED,
  WRONG_ITEM,
  NOT_AS_DESCRIBED,
  CHANGED_MIND,
  OTHER;

  /** Merchant fault: damaged items and the shipping fee are refunded (architecture §6.2). */
  public boolean merchantFault() {
    return this == DAMAGED || this == WRONG_ITEM || this == NOT_AS_DESCRIBED;
  }
}
