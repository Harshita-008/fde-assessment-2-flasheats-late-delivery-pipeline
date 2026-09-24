# Raw data profile (run 20260924T210041Z)
Generated from the raw snapshot before validation. Nothing here is cleaned.

### orders
1603 rows x 13 columns
- duplicate `order_id`: 3

| column | nulls | distinct | sample / range |
|---|---|---|---|
| order_id | 0 | 1600 | e.g. 'O00001' |
| customer_id | 0 | 727 | e.g. 'C0168' |
| restaurant_id | 3 | 60 | e.g. 'R009' |
| driver_id | 3 | 120 | e.g. 'D103' |
| city | 0 | 1 | 'Bengaluru':1603 |
| created_at | 0 | 1527 | 2026-08-01 11:02:00 → 2026-08-28 23:33:00; unparseable 0 |
| promised_eta | 0 | 1592 | 2026-08-01 12:17:48 → 2026-08-29 00:42:47.493150; unparseable 0 |
| pickup_at | 0 | 1600 | 2026-08-01 11:21:44.054049 → 2026-08-28 23:54:32.108716; unparseable 0 |
| actual_delivery_at | 105 | 1495 | 2026-08-01 12:07:11.607460 → 2026-08-29 00:50:53.383274; unparseable 0 |
| final_status | 0 | 3 | 'delivered':1530, 'cancelled':68, 'Delivered':5 |
| distance_km_estimate | 0 | 617 | min 0.5, median 18.0, max 45.0 |
| traffic_bucket | 0 | 5 | 'medium':635, 'high':448, 'low':381, 'severe':136, 'HIGH':3 |
| weather_bucket | 0 | 3 | 'clear':1276, 'rain':249, 'heavy_rain':78 |

### restaurants
60 rows x 6 columns
- duplicate `restaurant_id`: 0

| column | nulls | distinct | sample / range |
|---|---|---|---|
| restaurant_id | 0 | 60 | e.g. 'R001' |
| restaurant_name | 0 | 60 | e.g. 'Restaurant 001' |
| cuisine | 0 | 8 | 'South Indian':10, 'Cafe':10, 'North Indian':8, 'Biryani':8, 'Burgers':7, 'Chinese':7, 'Pizza':6, 'Desserts':4 |
| lat | 0 | 60 | min 12.738971, median 12.957245, max 95.12 |
| lon | 0 | 60 | min 77.385829, median 77.5960015, max 190.33 |
| manual_status_updates | 0 | 2 | min 0, median 0.0, max 1 |

### drivers
120 rows x 4 columns
- duplicate `driver_id`: 0

| column | nulls | distinct | sample / range |
|---|---|---|---|
| driver_id | 0 | 120 | e.g. 'D001' |
| rating | 0 | 64 | min 3.76, median 4.53, max 5.0 |
| vehicle_type | 0 | 3 | 'bike':69, 'scooter':40, 'ebike':11 |
| experience_months | 0 | 43 | min 1, median 19.0, max 83 |

### dispatch
1600 rows x 9 columns
- duplicate `order_id`: 0

| column | nulls | distinct | sample / range |
|---|---|---|---|
| assigned_at | 0 | 1600 | 2026-08-01 11:03:07.731329 → 2026-08-28 23:34:06.081673; unparseable 0 |
| current_delivery_eta | 0 | 1600 | 2026-08-01 12:17:48 → 2026-08-29 00:53:27.108992; unparseable 0 |
| dispatch_status | 0 | 2 | 'completed':1532, 'cancelled':68 |
| driver_id | 0 | 120 | e.g. 'D103' |
| estimated_pickup_at | 0 | 1527 | 2026-08-01 11:20:00 → 2026-08-28 23:51:00; unparseable 0 |
| eta_model_version | 0 | 2 | 'eta-v3.2':800, 'eta-v3.1':800 |
| order_id | 0 | 1600 | e.g. 'O00001' |
| original_driver_id | 0 | 120 | e.g. 'D103' |
| reassigned_at | 1505 | 95 | 2026-08-01 11:35:17.515941 → 2026-08-28 17:32:01.398186; unparseable 0 |

### driver_events
10035 rows x 6 columns

| column | nulls | distinct | sample / range |
|---|---|---|---|
| driver_id | 0 | 120 | e.g. 'D001' |
| order_id | 0 | 1600 | e.g. 'O00162' |
| type | 0 | 4 | 'gps_ping':5371, 'assigned':1600, 'picked_up':1532, 'delivered':1532 |
| timestamp | 0 | 10035 | 2026-08-01 11:03:07.731329 → 2026-08-29 00:50:53.383274; unparseable 0 |
| lat | 4664 | 5288 | min 12.744088, median 12.970018, max 81.446934 |
| lon | 4664 | 5293 | min 77.366498, median 77.602006, max 171.539239 |

### interventions
430 rows x 6 columns
- duplicate `intervention_id`: 0

| column | nulls | distinct | sample / range |
|---|---|---|---|
| intervention_id | 0 | 430 | e.g. 'INT-00001' |
| order_id | 0 | 430 | e.g. 'O00781' |
| intervention_type | 0 | 4 | 'DRIVER_REASSIGNMENT':155, 'RESTAURANT_CONTACT':116, 'PRIORITY_DISPATCH':95, 'CUSTOMER_CREDIT':64 |
| intervention_at | 0 | 425 | 2026-08-01 11:39:00 → 2026-08-28 23:33:48; unparseable 0 |
| initiated_by | 0 | 3 | 'support':180, 'dispatch':155, 'operations':95 |
| reason | 0 | 12 | 'slow_progress':58, 'driver_unavailable':51, 'capacity_rebalance':46, 'customer_escalation':40, 'status_stale':38, 'prep_delay':38, 'late_risk':36, 'vip_customer':33, 'support_resolution':26, 'manual_ops_review':26, 'late_delivery':20, 'service_recovery':18 |

### outcomes_reference
1600 rows x 6 columns
- duplicate `order_id`: 0

| column | nulls | distinct | sample / range |
|---|---|---|---|
| order_id | 0 | 1600 | e.g. 'O00001' |
| final_status_norm | 0 | 2 | 'delivered':1532, 'cancelled':68 |
| delivered_flag | 0 | 2 | min 0, median 1.0, max 1 |
| late_flag | 105 | 2 | min 0.0, median 1.0, max 1.0 |
| delay_min | 105 | 1224 | min -22.15, median 1.41, max 87.35 |
| outcome_bucket | 0 | 4 | 'delivered_late':843, 'delivered_on_time':652, 'cancelled':68, 'unknown':37 |
