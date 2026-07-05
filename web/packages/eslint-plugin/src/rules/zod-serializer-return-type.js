/** @type {import('eslint').Rule.RuleModule} */
export default {
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description:
        "Require explicit return type on methods decorated with @ZodSerializerDto",
    },
    messages: {
      missingReturnType:
        "Method decorated with @ZodSerializerDto({{ dtoName }}) must have an explicit return type annotation (e.g., Promise<{{ dtoName }}>).",
    },
    schema: [],
  },
  create(context) {
    return {
      MethodDefinition(node) {
        if (!node.decorators?.length) return;

        for (const decorator of node.decorators) {
          const expr = decorator.expression;
          if (
            expr.type !== "CallExpression" ||
            expr.callee.type !== "Identifier" ||
            expr.callee.name !== "ZodSerializerDto"
          )
            continue;

          const dtoArg = expr.arguments[0];
          const dtoName = dtoArg?.type === "Identifier" ? dtoArg.name : null;

          const fn = node.value;
          if (!fn.returnType) {
            context.report({
              node: node.key,
              messageId: "missingReturnType",
              data: { dtoName: dtoName ?? "Dto" },
              fix: dtoName
                ? (fixer) => {
                    const sourceCode = context.sourceCode;
                    const closeParen = sourceCode.getTokenBefore(fn.body);
                    return fixer.insertTextAfter(
                      closeParen,
                      `: Promise<${dtoName}>`,
                    );
                  }
                : null,
            });
          }
        }
      },
    };
  },
};
