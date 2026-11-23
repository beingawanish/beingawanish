package com.edacommerce.fulfilment.application;

import com.edacommerce.fulfilment.domain.ReturnIntake;
import java.util.Optional;

/** Port: expected and received returns, keyed by returnId. */
public interface ReturnIntakeRepository {
  Optional<ReturnIntake> findIntakeForUpdate(String returnId);

  void saveIntake(ReturnIntake intake);
}
