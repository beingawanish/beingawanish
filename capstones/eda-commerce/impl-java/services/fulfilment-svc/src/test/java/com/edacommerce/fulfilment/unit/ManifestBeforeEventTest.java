package com.edacommerce.fulfilment.unit;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.errors.TransientException;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.fulfilment.application.FulfilmentRepository;
import com.edacommerce.fulfilment.application.FulfilmentUseCases;
import com.edacommerce.fulfilment.application.ReturnIntakeRepository;
import com.edacommerce.fulfilment.application.Warehouse;
import com.edacommerce.fulfilment.domain.Fulfilment;
import com.edacommerce.fulfilment.domain.Parcel;
import java.time.Clock;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Object first, event second (ADR-0009, chaos-minio): when the manifest cannot be stored, nothing
 * is written (no transaction is even opened) and the failure goes back to the warehouse callback,
 * which repeats it.
 */
class ManifestBeforeEventTest {
  @Test
  void aFailedUploadWritesNoEvent() {
    FulfilmentRepository repo = mock(FulfilmentRepository.class);
    ClaimCheckStore store = mock(ClaimCheckStore.class);
    OutboxWriter outbox = mock(OutboxWriter.class);
    TransactionTemplate tx = mock(TransactionTemplate.class);
    Fulfilment f = FulfilmentTest.requested();
    f.accept("wh", FulfilmentTest.T, FulfilmentTest.T);
    f.pick(FulfilmentTest.T);
    when(repo.find("f1")).thenReturn(Optional.of(f));
    when(store.put(anyString(), anyString(), any(), anyString(), any()))
        .thenThrow(new TransientException("object storage unreachable"));
    FulfilmentUseCases useCases =
        new FulfilmentUseCases(
            repo,
            mock(ReturnIntakeRepository.class),
            mock(Warehouse.class),
            store,
            outbox,
            tx,
            Clock.systemUTC());

    assertThatThrownBy(
            () -> useCases.packed("f1", List.of(new Parcel("p", 1, 1, 1, 1)), new byte[] {1}))
        .isInstanceOf(TransientException.class);
    verify(tx, never()).executeWithoutResult(any());
    verify(outbox, never()).append(any(), any());
  }
}
