-- Seed default fallback review for demo and health probe telemetry
insert into reviews (review_id)
values ('demo')
on conflict (review_id) do nothing;
