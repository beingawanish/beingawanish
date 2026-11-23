package com.edacommerce.order.application;

import com.edacommerce.order.domain.OrderSagaData;

/** Port: saga data <-> the JSON stored in saga_instance.data. */
public interface SagaDataCodec {
  String write(OrderSagaData data);

  OrderSagaData read(String json);
}
