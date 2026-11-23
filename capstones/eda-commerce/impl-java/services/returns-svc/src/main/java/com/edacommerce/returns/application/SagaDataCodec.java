package com.edacommerce.returns.application;

import com.edacommerce.returns.domain.ReturnSagaData;

/** Port: saga_instance.data <-> domain data. */
public interface SagaDataCodec {
  String write(ReturnSagaData data);

  ReturnSagaData read(String json);
}
