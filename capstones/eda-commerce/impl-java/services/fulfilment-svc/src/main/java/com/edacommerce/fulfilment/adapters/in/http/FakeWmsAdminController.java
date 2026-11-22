package com.edacommerce.fulfilment.adapters.in.http;

import com.edacommerce.fulfilment.adapters.out.wms.fake.FakeWms;
import com.edacommerce.fulfilment.adapters.out.wms.fake.FakeWmsConfig;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** {@code PUT /admin/fakes/wms} (admin.yaml): the chaos drills turn these knobs. */
@RestController
public class FakeWmsAdminController {
  private final FakeWms wms;

  public FakeWmsAdminController(FakeWms wms) {
    this.wms = wms;
  }

  /** Not in admin.yaml; a convenience for operators, like GET /admin/fakes/psp. */
  @GetMapping("/admin/fakes/wms")
  public FakeWmsConfig get() {
    return wms.config();
  }

  /** Merges the given fields into the current behaviour; omitted fields keep their value. */
  @PutMapping("/admin/fakes/wms")
  public ResponseEntity<Void> put(@RequestBody FakeWmsConfig patch) {
    wms.update(patch);
    return ResponseEntity.ok().build();
  }
}
