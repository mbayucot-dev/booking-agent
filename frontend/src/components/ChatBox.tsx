"use client";

import { Loader2, Send } from "lucide-react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export interface ChatBoxProps {
  onSubmit: (message: string) => void;
  pending?: boolean;
}

type ChatForm = { message: string };

const REQUIRED_MSG = "Enter a booking request to continue.";

// No zodResolver: handleSubmit reads element.value from the DOM ref directly —
// synthetic onChange doesn't fire reliably under Playwright in production Next.js builds.
export function ChatBox({ onSubmit, pending }: ChatBoxProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ChatForm>({ defaultValues: { message: "" } });

  return (
    <form
      onSubmit={handleSubmit(({ message }) => onSubmit(message.trim()))}
      className="space-y-3"
    >
      <div className="space-y-2">
        <Label htmlFor="message">Booking message</Label>
        <Textarea
          id="message"
          placeholder="Describe the booking, e.g. 'Book a plumber for Tuesday 9am for Jane Doe'"
          rows={3}
          disabled={pending}
          className="resize-y"
          aria-describedby="message-desc"
          aria-invalid={!!errors.message}
          {...register("message", {
            required: REQUIRED_MSG,
            validate: (v) => v.trim().length > 0 || REQUIRED_MSG,
          })}
        />
        <p id="message-desc" className="text-[0.8rem] text-muted-foreground">
          Natural language — the agents extract the structured request.
        </p>
        {errors.message && (
          <p role="alert" className="text-[0.8rem] font-medium text-destructive">
            {errors.message.message}
          </p>
        )}
      </div>
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? (
          <>
            <Loader2 className="animate-spin" aria-hidden="true" />
            Starting…
          </>
        ) : (
          <>
            <Send aria-hidden="true" />
            Submit
          </>
        )}
      </Button>
    </form>
  );
}
