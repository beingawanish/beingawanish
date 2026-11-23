package com.edacommerce.order.application;

import com.edacommerce.order.domain.Order;
import com.edacommerce.order.domain.OrderStatus;
import java.util.Optional;

/** Port: the order write model (orders, order_line). */
public interface OrderRepository {
  void insert(Order order);

  Optional<Order> find(String orderId);

  void updateStatus(String orderId, OrderStatus status);

  Optional<OrderStatus> status(String orderId);
}
