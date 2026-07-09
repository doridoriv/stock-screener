# Feedback setup

The app supports a lightweight "하고 싶은 말" feedback box with public/private posts and admin soft-delete.

## Streamlit secrets

Set these values in Streamlit Cloud secrets:

```toml
FEEDBACK_SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
FEEDBACK_SUPABASE_KEY = "YOUR_SUPABASE_SERVICE_ROLE_OR_POLICY_KEY"
FEEDBACK_ADMIN_PASSWORD = "CHANGE_ME"
```

## Supabase table

Run this SQL in Supabase:

```sql
create table if not exists feedback_messages (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  visibility text not null check (visibility in ('public', 'private')),
  category text not null,
  message text not null check (char_length(message) between 3 and 1200),
  market text,
  view_mode text,
  lens text,
  is_deleted boolean not null default false
);

create index if not exists feedback_messages_public_idx
  on feedback_messages (created_at desc)
  where visibility = 'public' and is_deleted = false;

create index if not exists feedback_messages_admin_idx
  on feedback_messages (created_at desc)
  where is_deleted = false;
```

The app performs deletes as `is_deleted = true` so accidental deletes can still be recovered from Supabase.
