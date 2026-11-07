# u-blox dynamic-model defaults in open flight stacks (recorded 2026-11-07 10:38 UTC)

## PX4 v1.16.0 multicopter defaults

[`ROMFS/px4fmu_common/init.d/rc.mc_defaults`](https://github.com/PX4/PX4-Autopilot/blob/6ea3539157ca358c70a515878b77077af7d4611d/ROMFS/px4fmu_common/init.d/rc.mc_defaults) at v1.16.0 (`6ea3539157ca`)

```
23: param set-default GPS_UBX_DYNMODEL 6
```

## PX4 v1.17.0 multicopter defaults

[`ROMFS/px4fmu_common/init.d/rc.mc_defaults`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/ROMFS/px4fmu_common/init.d/rc.mc_defaults) at v1.17.0 (`d6f12ad1c4f7`)

No line matches `GPS_UBX_DYNMODEL`.

## PX4 v1.17.0 fixed-wing defaults

[`ROMFS/px4fmu_common/init.d/rc.fw_defaults`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/ROMFS/px4fmu_common/init.d/rc.fw_defaults) at v1.17.0 (`d6f12ad1c4f7`)

```
50: param set-default GPS_UBX_DYNMODEL 8
```

## PX4 v1.17.0 parameter default

[`src/drivers/gps/params.c`](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/drivers/gps/params.c) at v1.17.0 (`d6f12ad1c4f7`)

```
70: PARAM_DEFINE_INT32(GPS_UBX_DYNMODEL, 7);
```

## ArduPilot master

[`libraries/AP_GPS/AP_GPS.cpp`](https://github.com/ArduPilot/ardupilot/blob/b7c08d4dbc69f58f5636642698b63a9130725db6/libraries/AP_GPS/AP_GPS.cpp) at master (`b7c08d4dbc69`)

```
128:     // @Param: _NAVFILTER
133:     AP_GROUPINFO("_NAVFILTER", 2, AP_GPS, _navfilter, GPS_ENGINE_AIRBORNE_4G),
```

## Betaflight master

[`src/main/pg/gps.c`](https://github.com/betaflight/betaflight/blob/bfb608d25aefd4787a8273ca0b6a320cafbdf5e7/src/main/pg/gps.c) at master (`bfb608d25aef`)

```
44:     .gps_ublox_acquire_model = UBLOX_MODEL_STATIONARY,
45:     .gps_ublox_flight_model = UBLOX_MODEL_AIRBORNE_4G,
```

## INAV master

[`src/main/fc/settings.yaml`](https://github.com/iNavFlight/inav/blob/940b9281bbefb06b85d442ac5b456c81ae8672c9/src/main/fc/settings.yaml) at master (`940b9281bbef`)

```
50:   - name: gps_dyn_model
51:     values: ["PEDESTRIAN","AUTOMOTIVE", "AIR_1G", "AIR_2G", "AIR_4G", "SEA", "MOWER"]
52:     enum: gpsDynModel_e
53:   - name: reset_type
54:     values: ["NEVER", "FIRST_ARM", "EACH_ARM"]
55:   - name: direction
56:     values: ["RIGHT", "LEFT", "YAW"]
1736:       - name: gps_dyn_model
1737:         description: "GPS navigation model: Pedestrian, Automotive, Air<1g, Air<2g, Air<4g. Default is AIR_2G. Use pedestrian/Automotive with caution, can cause flyaways with fast flying."
1738:         default_value: "AIR_2G"
1739:         field: dynModel
1740:         table: gps_dyn_model
1741:         type: uint8_t
1742:       - name: gps_auto_config
```

