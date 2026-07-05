import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import {
  AdminOrganizationResponseSchema,
  AdminUpdateOrganizationRequestSchema,
} from "@shelfalign/schema/dtos/admin/organization";

import { ky } from "@/lib/ky";

import { queries } from "@/queries";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";

export const Route = createFileRoute(
  "/_app/organizations/$organizationId/edit",
)({
  component: EditOrganizationPage,
});

function EditOrganizationPage() {
  const { organizationId } = Route.useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: organization } = useSuspenseQuery(
    queries.organization.get(organizationId),
  );

  const form = useForm({
    resolver: zodResolver(AdminUpdateOrganizationRequestSchema),
    defaultValues: {
      name: organization.name,
    },
  });

  const { mutate, isPending } = useMutation({
    mutationFn: async (
      values: z.infer<typeof AdminUpdateOrganizationRequestSchema>,
    ) => {
      const res = await ky.patch(
        `${import.meta.env.VITE_BASE_URL}/admin/organizations/${organizationId}`,
        { json: values },
      );
      const response = await tryJson(
        await res.text(),
        AdminOrganizationResponseSchema,
      );
      return toastParseError(res, response);
    },
    onSuccess: () => {
      toast.success("조직 수정 완료");
      queryClient.invalidateQueries({
        queryKey: queries.organization.list._def,
      });
      queryClient.invalidateQueries({
        queryKey: queries.organization.get(organizationId).queryKey,
      });
      navigate({
        to: "/organizations/$organizationId",
        params: { organizationId },
      });
    },
  });

  const handleCancel = () => {
    navigate({
      to: "/organizations/$organizationId",
      params: { organizationId },
    });
  };

  return (
    <>
      <Breadcrumb
        items={[
          { type: "link", label: "조직 관리", to: "/organizations" },
          {
            type: "link",
            label: organization.name,
            to: "/organizations/$organizationId",
            params: { organizationId },
          },
          { type: "text", label: "수정" },
        ]}
      />
      <h2 className="font-extrabold text-xl my-3">조직 수정</h2>

      <Card>
        <CardHeader>
          <CardTitle>조직 정보 수정</CardTitle>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit((values) => mutate(values))}
              className="space-y-4"
            >
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>이름</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="조직 이름"
                        autoComplete="organization"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div className="flex gap-2 justify-end">
                <Button type="button" variant="outline" onClick={handleCancel}>
                  취소
                </Button>
                <Button type="submit" disabled={isPending}>
                  {isPending ? "저장 중..." : "저장"}
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>
    </>
  );
}
