# GKI kernel — Redmi Note 12 4G (tapas)

Google'ın android13-5.15 GKI kernel'ini, Google CI'daki bir sertifikalı build'in
kaynaklarıyla (manifest'teki commit'lerle) ve aynı komutla (`build/build.sh`)
derler. Flash'lamadan önce şunları kontrol eder:

- **KMI:** `vmlinux.symvers` Google'ın build'iyle aynı olmalı (aynı semboller, aynı CRC'ler).
- **Vendor modülleri:** Telefondaki `vendor_dlkm` ve `vendor_ramdisk` modüllerinin
  istediği her sembol bu kernel'de aynı CRC ile bulunmalı (`scripts/check_vendor_abi.py`).
- **boot.img:** Telefondaki `boot.img`'in başlığı ve AVB bilgileri (OS sürümü, SPL,
  rollback index, imza anahtarı) aynen korunur, yalnızca kernel değişir
  (`scripts/make_boot.py`). Betik önce eski kernel'le eski imajı bayt bayt yeniden üretip kendini test eder.
- **system_dlkm.img:** zram/zsmalloc modülleri bu build'in anahtarıyla imzalıdır, kernel'le birlikte flash'lanmalı.

## Kaynak (GPLv2)

Her release, derlenen `kernel/common` commit'inin kaynak arşivini
(`kernel-source-common-<sha>.tar.xz`) ve kullanılan tüm projeleri commit'leriyle
sabitleyen manifest'i (`manifest_<id>.xml`) içerir.

## Yeni sürüm

Actions → **Build GKI kernel** → `gki_bid` alanına yeni sertifikalı build'in id'sini yaz
([GKI android13-5.15 release builds](https://source.android.com/docs/core/architecture/kernel/gki-android13-5_15-release-builds)
sayfasındaki `ci.android.com/builds/submitted/<id>` bağlantısı). ROM güncellenince `base_boot`'u yeni ROM'un `boot.img`'i yap.

## Kurulum

```
fastboot boot boot.img                    # önce dene, hiçbir şey yazmaz
fastboot flash boot boot.img
fastboot reboot fastboot
fastboot flash system_dlkm system_dlkm.img
fastboot reboot
```

Geri dönüş: ROM release'indeki `boot.img`'i flash'la ve ROM zip'ini dirty flash yap.
