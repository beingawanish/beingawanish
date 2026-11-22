package com.edacommerce.returns.application;

/** No such order or return, or it belongs to another customer (returns.yaml 404). */
public class ReturnNotFoundException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public ReturnNotFoundException(String what) {
    super(what + " not found");
  }
}
